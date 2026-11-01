import smtplib

import pytest

from app.config.errors import ConfigurationError
from app.node.email_delivery import (
    DEFAULT_SMTP_PORT,
    EmailDeliveryError,
    SmtpSettings,
    load_smtp_settings,
    send_verification_code,
)

BASE_ENV = {
    "EWASTE_SMTP_HOST": "smtp.example.org",
    "EWASTE_SMTP_FROM": "codes@example.org",
}


class FakeSmtp:
    failure: BaseException | None = None
    instances: list["FakeSmtp"] = []

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host, self.port, self.timeout = host, port, timeout
        self.logins: list[tuple[str, str]] = []
        self.sent: list = []
        self.started_tls = False
        FakeSmtp.instances.append(self)

    def __enter__(self) -> "FakeSmtp":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def starttls(self, context: object) -> None:
        if FakeSmtp.failure is not None and isinstance(FakeSmtp.failure, smtplib.SMTPNotSupportedError):
            raise FakeSmtp.failure
        self.started_tls = True

    def login(self, username: str, password: str) -> None:
        if FakeSmtp.failure is not None and isinstance(FakeSmtp.failure, smtplib.SMTPAuthenticationError):
            raise FakeSmtp.failure
        self.logins.append((username, password))

    def send_message(self, message: object) -> None:
        if FakeSmtp.failure is not None and isinstance(FakeSmtp.failure, smtplib.SMTPRecipientsRefused):
            raise FakeSmtp.failure
        self.sent.append(message)


@pytest.fixture(autouse=True)
def reset_fake() -> None:
    FakeSmtp.failure = None
    FakeSmtp.instances = []


def _settings(**overrides: str) -> SmtpSettings:
    return load_smtp_settings({**BASE_ENV, **overrides})


def test_sends_code_over_starttls_with_login() -> None:
    settings = _settings(EWASTE_SMTP_USERNAME="mailer", EWASTE_SMTP_PASSWORD="secret-value")
    send_verification_code(settings, "alice@example.com", "123456", smtp_factory=FakeSmtp)
    server = FakeSmtp.instances[0]
    assert (server.host, server.port) == ("smtp.example.org", DEFAULT_SMTP_PORT)
    assert server.started_tls is True
    assert server.logins == [("mailer", "secret-value")]
    message = server.sent[0]
    assert message["To"] == "alice@example.com"
    assert message["From"] == "codes@example.org"
    assert "123456" in message.get_content()


def test_no_login_when_credentials_not_configured() -> None:
    send_verification_code(_settings(), "alice@example.com", "123456", smtp_factory=FakeSmtp)
    assert FakeSmtp.instances[0].logins == []


def test_refuses_server_without_starttls() -> None:
    FakeSmtp.failure = smtplib.SMTPNotSupportedError("STARTTLS not offered")
    with pytest.raises(EmailDeliveryError):
        send_verification_code(_settings(), "alice@example.com", "123456", smtp_factory=FakeSmtp)
    assert FakeSmtp.instances[0].sent == []


def test_rejected_login_is_reported_without_secret() -> None:
    FakeSmtp.failure = smtplib.SMTPAuthenticationError(535, b"bad credentials")
    settings = _settings(EWASTE_SMTP_USERNAME="mailer", EWASTE_SMTP_PASSWORD="secret-value")
    with pytest.raises(EmailDeliveryError) as raised:
        send_verification_code(settings, "alice@example.com", "123456", smtp_factory=FakeSmtp)
    assert "secret-value" not in str(raised.value)


def test_refused_recipient_is_reported() -> None:
    FakeSmtp.failure = smtplib.SMTPRecipientsRefused({"alice@example.com": (550, b"no such user")})
    with pytest.raises(EmailDeliveryError):
        send_verification_code(_settings(), "alice@example.com", "123456", smtp_factory=FakeSmtp)


def test_unreachable_server_is_reported() -> None:
    def unreachable(*args: object, **kwargs: object) -> FakeSmtp:
        raise ConnectionRefusedError("no route")

    with pytest.raises(EmailDeliveryError):
        send_verification_code(_settings(), "alice@example.com", "123456", smtp_factory=unreachable)


def test_invalid_recipient_is_refused_before_connecting() -> None:
    def must_not_connect(*args: object, **kwargs: object) -> FakeSmtp:
        raise AssertionError("no connection should be attempted")

    for recipient in ("", "no-at-sign", "alice@example.com\r\nBcc: x@example.com", "a b@example.com"):
        with pytest.raises(EmailDeliveryError):
            send_verification_code(_settings(), recipient, "123456", smtp_factory=must_not_connect)


def test_settings_require_host_and_sender() -> None:
    with pytest.raises(ConfigurationError, match="must be set"):
        load_smtp_settings({"EWASTE_SMTP_FROM": "codes@example.org"})
    with pytest.raises(ConfigurationError, match="must be set"):
        load_smtp_settings({"EWASTE_SMTP_HOST": "smtp.example.org"})


def test_settings_reject_invalid_sender_and_port() -> None:
    with pytest.raises(ConfigurationError, match="plain email"):
        load_smtp_settings({**BASE_ENV, "EWASTE_SMTP_FROM": "Codes <codes@example.org>"})
    with pytest.raises(ConfigurationError, match="whole number"):
        load_smtp_settings({**BASE_ENV, "EWASTE_SMTP_PORT": "submission"})
    with pytest.raises(ConfigurationError, match="between 1 and 65535"):
        load_smtp_settings({**BASE_ENV, "EWASTE_SMTP_PORT": "70000"})


def test_username_and_password_must_be_set_together() -> None:
    with pytest.raises(ConfigurationError, match="set together"):
        load_smtp_settings({**BASE_ENV, "EWASTE_SMTP_USERNAME": "mailer"})
    with pytest.raises(ConfigurationError, match="set together"):
        load_smtp_settings({**BASE_ENV, "EWASTE_SMTP_PASSWORD": "secret-value"})


def test_password_is_hidden_from_settings_representation() -> None:
    settings = _settings(EWASTE_SMTP_USERNAME="mailer", EWASTE_SMTP_PASSWORD="secret-value")
    assert "secret-value" not in repr(settings)
