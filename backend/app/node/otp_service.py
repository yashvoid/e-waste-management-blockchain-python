import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from collections.abc import Callable

from app.config.errors import ConfigurationError

OTP_STATE_FILE_NAME = "otp-state.json"
CODE_VALIDITY = timedelta(minutes=10)
MAX_FAILED_ATTEMPTS = 5
RESEND_INTERVAL = timedelta(seconds=60)
RESENDS_PER_HOUR = 3
_HOUR = timedelta(hours=1)


class OtpError(ValueError):
    pass


class OtpRateLimited(OtpError):
    pass


@dataclass
class _Challenge:
    digest: str
    expires_at: datetime
    failed_attempts: int
    sent_at: list[datetime]


class OtpService:
    def __init__(
        self,
        state_dir: Path,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._path = state_dir / OTP_STATE_FILE_NAME
        self._clock = clock
        self._salt, self._challenges = self._load()

    def request_code(self, email: str, send: Callable[[str], None]) -> None:
        now = self._clock()
        email_key = self._subject(email)
        challenge = self._challenges.get(email_key)
        if challenge is not None:
            recent = [moment for moment in challenge.sent_at if now - moment < _HOUR]
            if recent and now - recent[-1] < RESEND_INTERVAL:
                raise OtpRateLimited("Please wait before requesting another code.")
            if len(recent) > RESENDS_PER_HOUR:
                raise OtpRateLimited("Too many codes were requested for this address in the last hour.")
        else:
            recent = []

        code = f"{secrets.randbelow(1_000_000):06d}"
        send(code)
        self._challenges[email_key] = _Challenge(
            digest=self._digest(email_key, code),
            expires_at=now + CODE_VALIDITY,
            failed_attempts=0,
            sent_at=[*recent, now],
        )
        self._save()

    def verify_code(self, email: str, code: str) -> bool:
        now = self._clock()
        email_key = self._subject(email)
        challenge = self._challenges.get(email_key)
        if challenge is None or now >= challenge.expires_at:
            raise OtpError("The code has expired or was never requested. Request a new code.")
        if challenge.failed_attempts >= MAX_FAILED_ATTEMPTS:
            raise OtpError("Too many incorrect codes. Request a new code.")

        if hmac.compare_digest(challenge.digest, self._digest(email_key, code)):
            challenge.digest = ""
            challenge.expires_at = now
            self._save()
            return True

        challenge.failed_attempts += 1
        self._save()
        return False

    def _subject(self, email: str) -> str:
        return hmac.new(bytes.fromhex(self._salt), f"subject\n{email}".encode("utf-8"), hashlib.sha256).hexdigest()

    def _digest(self, email_key: str, code: str) -> str:
        return hmac.new(bytes.fromhex(self._salt), f"{email_key}\n{code}".encode("utf-8"), hashlib.sha256).hexdigest()

    def _load(self) -> tuple[str, dict[str, _Challenge]]:
        if not self._path.exists():
            return secrets.token_hex(32), {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            salt = raw["salt"]
            bytes.fromhex(salt)
            challenges = {
                key: _Challenge(
                    digest=value["digest"],
                    expires_at=datetime.fromisoformat(value["expires_at"]),
                    failed_attempts=int(value["failed_attempts"]),
                    sent_at=[datetime.fromisoformat(moment) for moment in value["sent_at"]],
                )
                for key, value in raw["challenges"].items()
            }
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ConfigurationError("The OTP state file is damaged and was not overwritten.") from exc
        return salt, challenges

    def _save(self) -> None:
        document = {
            "salt": self._salt,
            "challenges": {
                key: {
                    "digest": value.digest,
                    "expires_at": value.expires_at.isoformat(),
                    "failed_attempts": value.failed_attempts,
                    "sent_at": [moment.isoformat() for moment in value.sent_at],
                }
                for key, value in self._challenges.items()
            },
        }
        temporary = self._path.with_name(self._path.name + ".tmp")
        with temporary.open("wb") as handle:
            handle.write(json.dumps(document, sort_keys=True).encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self._path)
