import smtplib
import ssl
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from email.message import EmailMessage

from app.config.errors import ConfigurationError

SMTP_HOST_ENV = "EWASTE_SMTP_HOST"
SMTP_PORT_ENV = "EWASTE_SMTP_PORT"
SMTP_USERNAME_ENV = "EWASTE_SMTP_USERNAME"
SMTP_PASSWORD_ENV = "EWASTE_SMTP_PASSWORD"
SMTP_FROM_ENV = "EWASTE_SMTP_FROM"
SMTP_TIMEOUT_SECONDS = 15.0
DEFAULT_SMTP_PORT = 587

SMTP_FACTORY = Callable[..., smtplib.SMTP]


class EmailDeliveryError(Exception):
    pass


@dataclass(frozen=True)
class SmtpSettings:
    host: str
    port: int
    sender: str
    username: str | None = None
    password: str | None = field(default=None, repr=False)


def load_smtp_settings(environ: Mapping[str, str]) -> SmtpSettings:
    host = environ.get(SMTP_HOST_ENV, "").strip()
    sender = environ.get(SMTP_FROM_ENV, "").strip()
    if not host or not sender:
        raise ConfigurationError(
            f"{SMTP_HOST_ENV} and {SMTP_FROM_ENV} must be set to send verification emails."
        )
    if not _plain_address(sender):
        raise ConfigurationError(f"{SMTP_FROM_ENV} must be a plain email address.")
    port = _parse_port(environ.get(SMTP_PORT_ENV, "").strip() or str(DEFAULT_SMTP_PORT))
    username = environ.get(SMTP_USERNAME_ENV, "").strip() or None
    password = environ.get(SMTP_PASSWORD_ENV, "") or None
    if (username is None) != (password is None):
        raise ConfigurationError(
            f"{SMTP_USERNAME_ENV} and {SMTP_PASSWORD_ENV} must be set together."
        )
    return SmtpSettings(host=host, port=port, sender=sender, username=username, password=password)


def send_verification_code(
    settings: SmtpSettings,
    recipient: str,
    code: str,
    *,
    smtp_factory: SMTP_FACTORY = smtplib.SMTP,
) -> None:
    if not _plain_address(recipient):
        raise EmailDeliveryError("The email address is not valid.")
    message = EmailMessage()
    message["From"] = settings.sender
    message["To"] = recipient
    message["Subject"] = "Your verification code"
    message.set_content(
        f"Your verification code is {code}. It expires in 10 minutes.\n\n"
        "If you did not ask for this code, you can ignore this email."
    )
    try:
        with smtp_factory(settings.host, settings.port, timeout=SMTP_TIMEOUT_SECONDS) as server:
            server.starttls(context=ssl.create_default_context())
            if settings.username is not None and settings.password is not None:
                server.login(settings.username, settings.password)
            server.send_message(message)
    except (smtplib.SMTPException, OSError, ssl.SSLError, ValueError) as exc:
        raise EmailDeliveryError("The verification email could not be sent. Try again later.") from exc


def _parse_port(text: str) -> int:
    try:
        port = int(text)
    except ValueError as exc:
        raise ConfigurationError(f"{SMTP_PORT_ENV} must be a whole number.") from exc
    if not 1 <= port <= 65535:
        raise ConfigurationError(f"{SMTP_PORT_ENV} must be between 1 and 65535.")
    return port


def _plain_address(address: str) -> bool:
    local, separator, domain = address.partition("@")
    return bool(separator and local and "." in domain and not any(ch.isspace() or ord(ch) < 32 for ch in address))
