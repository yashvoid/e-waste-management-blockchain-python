from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.config.errors import ConfigurationError
from app.node.otp_service import (
    CODE_VALIDITY,
    MAX_FAILED_ATTEMPTS,
    OTP_STATE_FILE_NAME,
    RESEND_INTERVAL,
    RESENDS_PER_HOUR,
    OtpError,
    OtpRateLimited,
    OtpService,
)

START = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)
EMAIL = "alice@example.com"


class Clock:
    def __init__(self) -> None:
        self.moment = START

    def __call__(self) -> datetime:
        return self.moment

    def advance(self, delta: timedelta) -> None:
        self.moment += delta


class Outbox:
    def __init__(self) -> None:
        self.codes: list[str] = []

    def __call__(self, code: str) -> None:
        self.codes.append(code)


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "otp"
    directory.mkdir()
    return directory


def _issue(service: OtpService, outbox: Outbox) -> str:
    service.request_code(EMAIL, outbox)
    return outbox.codes[-1]


def test_correct_code_verifies_once(state_dir: Path) -> None:
    clock, outbox = Clock(), Outbox()
    service = OtpService(state_dir, clock=clock)
    code = _issue(service, outbox)
    assert len(code) == 6 and code.isdigit()
    assert service.verify_code(EMAIL, code) is True
    with pytest.raises(OtpError):
        service.verify_code(EMAIL, code)


def test_successful_verification_does_not_reset_resend_limits(state_dir: Path) -> None:
    clock, outbox = Clock(), Outbox()
    service = OtpService(state_dir, clock=clock)
    code = _issue(service, outbox)
    assert service.verify_code(EMAIL, code) is True
    for _ in range(RESENDS_PER_HOUR):
        clock.advance(RESEND_INTERVAL)
        service.request_code(EMAIL, outbox)
    clock.advance(RESEND_INTERVAL)
    with pytest.raises(OtpRateLimited, match="Too many"):
        service.request_code(EMAIL, outbox)


def test_wrong_code_is_refused(state_dir: Path) -> None:
    clock, outbox = Clock(), Outbox()
    service = OtpService(state_dir, clock=clock)
    code = _issue(service, outbox)
    wrong = "000000" if code != "000000" else "111111"
    assert service.verify_code(EMAIL, wrong) is False


def test_code_expires_after_ten_minutes(state_dir: Path) -> None:
    clock, outbox = Clock(), Outbox()
    service = OtpService(state_dir, clock=clock)
    code = _issue(service, outbox)
    clock.advance(CODE_VALIDITY - timedelta(seconds=1))
    assert service.verify_code(EMAIL, code) is True

    clock.advance(RESEND_INTERVAL)
    code = _issue(service, outbox)
    clock.advance(CODE_VALIDITY)
    with pytest.raises(OtpError, match="expired"):
        service.verify_code(EMAIL, code)


def test_five_failed_attempts_lock_the_code(state_dir: Path) -> None:
    clock, outbox = Clock(), Outbox()
    service = OtpService(state_dir, clock=clock)
    code = _issue(service, outbox)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(MAX_FAILED_ATTEMPTS):
        assert service.verify_code(EMAIL, wrong) is False
    with pytest.raises(OtpError, match="Too many"):
        service.verify_code(EMAIL, code)


def test_resend_requires_sixty_second_interval(state_dir: Path) -> None:
    clock, outbox = Clock(), Outbox()
    service = OtpService(state_dir, clock=clock)
    _issue(service, outbox)
    clock.advance(RESEND_INTERVAL - timedelta(seconds=1))
    with pytest.raises(OtpRateLimited, match="wait"):
        service.request_code(EMAIL, outbox)
    clock.advance(timedelta(seconds=1))
    service.request_code(EMAIL, outbox)
    assert len(outbox.codes) == 2


def test_three_resends_per_hour_are_allowed_then_refused(state_dir: Path) -> None:
    clock, outbox = Clock(), Outbox()
    service = OtpService(state_dir, clock=clock)
    _issue(service, outbox)
    for _ in range(RESENDS_PER_HOUR):
        clock.advance(RESEND_INTERVAL)
        service.request_code(EMAIL, outbox)
    clock.advance(RESEND_INTERVAL)
    with pytest.raises(OtpRateLimited, match="Too many"):
        service.request_code(EMAIL, outbox)
    assert len(outbox.codes) == RESENDS_PER_HOUR + 1


def test_hourly_quota_recovers_after_an_hour(state_dir: Path) -> None:
    clock, outbox = Clock(), Outbox()
    service = OtpService(state_dir, clock=clock)
    _issue(service, outbox)
    for _ in range(RESENDS_PER_HOUR):
        clock.advance(RESEND_INTERVAL)
        service.request_code(EMAIL, outbox)
    clock.advance(timedelta(hours=1))
    service.request_code(EMAIL, outbox)
    assert len(outbox.codes) == RESENDS_PER_HOUR + 2


def test_resend_limit_survives_restart(state_dir: Path) -> None:
    clock, outbox = Clock(), Outbox()
    service = OtpService(state_dir, clock=clock)
    _issue(service, outbox)
    for _ in range(RESENDS_PER_HOUR):
        clock.advance(RESEND_INTERVAL)
        service.request_code(EMAIL, outbox)

    restarted = OtpService(state_dir, clock=clock)
    clock.advance(RESEND_INTERVAL)
    with pytest.raises(OtpRateLimited, match="Too many"):
        restarted.request_code(EMAIL, outbox)


def test_failed_attempts_survive_restart(state_dir: Path) -> None:
    clock, outbox = Clock(), Outbox()
    service = OtpService(state_dir, clock=clock)
    code = _issue(service, outbox)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(MAX_FAILED_ATTEMPTS):
        service.verify_code(EMAIL, wrong)

    restarted = OtpService(state_dir, clock=clock)
    with pytest.raises(OtpError, match="Too many"):
        restarted.verify_code(EMAIL, code)


def test_send_failure_does_not_consume_a_resend(state_dir: Path) -> None:
    clock, outbox = Clock(), Outbox()
    service = OtpService(state_dir, clock=clock)

    def failing_send(_: str) -> None:
        raise RuntimeError("provider unavailable")

    with pytest.raises(RuntimeError):
        service.request_code(EMAIL, failing_send)
    service.request_code(EMAIL, outbox)
    assert len(outbox.codes) == 1


def test_state_file_stores_no_plaintext_email_or_code(state_dir: Path) -> None:
    clock, outbox = Clock(), Outbox()
    service = OtpService(state_dir, clock=clock)
    code = _issue(service, outbox)
    stored = (state_dir / OTP_STATE_FILE_NAME).read_text(encoding="utf-8")
    assert EMAIL not in stored
    assert code not in stored


def test_damaged_state_file_is_refused_not_overwritten(state_dir: Path) -> None:
    path = state_dir / OTP_STATE_FILE_NAME
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="damaged"):
        OtpService(state_dir)
    assert path.read_text(encoding="utf-8") == "{not json"
