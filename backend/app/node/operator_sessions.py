import secrets
import threading
import time
from collections.abc import Callable

from app.crypto.password_verifier import verify_password

SESSION_IDLE_SECONDS = 15 * 60
MAX_FAILED_SIGN_INS = 5
SIGN_IN_LOCKOUT_SECONDS = 15 * 60


class OperatorNotConfigured(Exception):
    pass


class InvalidOperatorPassword(Exception):
    pass


class SignInLocked(Exception):
    pass


class OperatorSessions:
    def __init__(self, verifier: str | None, clock: Callable[[], float] = time.monotonic) -> None:
        self._verifier = verifier
        self._clock = clock
        self._lock = threading.Lock()
        self._last_seen: dict[str, float] = {}
        self._failed_sign_ins = 0
        self._locked_until = 0.0

    def sign_in(self, password: str) -> str:
        if self._verifier is None:
            raise OperatorNotConfigured()
        with self._lock:
            if self._clock() < self._locked_until:
                raise SignInLocked()
        if not verify_password(password, self._verifier):
            with self._lock:
                self._failed_sign_ins += 1
                if self._failed_sign_ins >= MAX_FAILED_SIGN_INS:
                    self._locked_until = self._clock() + SIGN_IN_LOCKOUT_SECONDS
                    self._failed_sign_ins = 0
            raise InvalidOperatorPassword()
        token = secrets.token_urlsafe(32)
        with self._lock:
            now = self._clock()
            self._failed_sign_ins = 0
            self._purge_expired(now)
            self._last_seen[token] = now
        return token

    def is_active(self, token: str) -> bool:
        with self._lock:
            now = self._clock()
            self._purge_expired(now)
            if token not in self._last_seen:
                return False
            self._last_seen[token] = now
            return True

    def sign_out(self, token: str) -> None:
        with self._lock:
            self._last_seen.pop(token, None)

    def _purge_expired(self, now: float) -> None:
        expired = [token for token, seen in self._last_seen.items() if now - seen >= SESSION_IDLE_SECONDS]
        for token in expired:
            del self._last_seen[token]
