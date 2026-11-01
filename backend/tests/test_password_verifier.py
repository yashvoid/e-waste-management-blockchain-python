import pytest

from app.config.errors import ConfigurationError
from app.config.node_settings import OPERATOR_VERIFIER_ENV, load_node_settings
from app.crypto import password_verifier
from app.crypto.password_verifier import make_verifier, validate_verifier, verify_password
from app.node import provision

PASSWORD = "correct-horse-battery"


@pytest.fixture(scope="module")
def verifier() -> str:
    return make_verifier(PASSWORD)


def test_verifier_accepts_the_original_password(verifier):
    assert verify_password(PASSWORD, verifier) is True


def test_verifier_rejects_other_passwords(verifier):
    assert verify_password("correct-horse-battery!", verifier) is False
    assert verify_password("", verifier) is False


def test_verifier_uses_a_fresh_salt_each_time(verifier):
    assert make_verifier(PASSWORD) != verifier


def test_verifier_does_not_contain_the_password(verifier):
    assert PASSWORD not in verifier


def test_verifier_has_the_expected_scrypt_format(verifier):
    scheme, n, r, p, salt, digest = verifier.split("$")
    assert scheme == "scrypt"
    assert (int(n), int(r), int(p)) == (2**14, 8, 1)
    assert len(bytes.fromhex(salt)) == 16
    assert len(bytes.fromhex(digest)) == 32


@pytest.mark.parametrize("password", ["", "short", "a" * 11, "y" * 257])
def test_passwords_outside_the_length_bounds_are_rejected(password):
    with pytest.raises(ValueError):
        make_verifier(password)


def test_shortest_and_longest_allowed_passwords_work():
    assert verify_password("a" * 12, make_verifier("a" * 12))
    assert verify_password("b" * 256, make_verifier("b" * 256))


@pytest.mark.parametrize(
    "malformed",
    [
        "",
        "scrypt",
        "bcrypt$16384$8$1$00$00",
        "scrypt$16383$8$1$" + "00" * 16 + "$" + "00" * 32,
        "scrypt$16384$0$1$" + "00" * 16 + "$" + "00" * 32,
        "scrypt$16384$8$1$zz$" + "00" * 32,
        "scrypt$16384$8$1$" + "00" * 4 + "$" + "00" * 32,
        "scrypt$16384$8$1$" + "00" * 16 + "$" + "00" * 8,
        "scrypt$16384$8$1$" + "00" * 16,
    ],
)
def test_malformed_verifiers_are_rejected(malformed):
    with pytest.raises(ValueError):
        validate_verifier(malformed)


def test_verify_password_rejects_malformed_verifier():
    with pytest.raises(ValueError):
        verify_password(PASSWORD, "not-a-verifier")


def base_environ(**extra: str) -> dict[str, str]:
    environ = {
        "EWASTE_NODE_ID": "node-a",
        "EWASTE_LISTEN_HOST": "127.0.0.1",
        "EWASTE_LISTEN_PORT": "8000",
        "EWASTE_PEER_PORT": "8443",
        "EWASTE_DATA_DIR": "/tmp/data",
        "EWASTE_IDENTITY_DIR": "/tmp/identity",
        "EWASTE_NETWORK_CONFIG": "/tmp/network.json",
    }
    environ.update(extra)
    return environ


def test_operator_verifier_is_optional():
    assert load_node_settings(base_environ()).operator_verifier is None


def test_valid_operator_verifier_is_loaded(verifier):
    settings = load_node_settings(base_environ(**{OPERATOR_VERIFIER_ENV: verifier}))
    assert settings.operator_verifier == verifier


def test_malformed_operator_verifier_stops_configuration():
    with pytest.raises(ConfigurationError) as excinfo:
        load_node_settings(base_environ(**{OPERATOR_VERIFIER_ENV: "scrypt$bad"}))
    assert "set-operator-password" in str(excinfo.value)
    assert "scrypt$bad" not in str(excinfo.value)


def test_provisioning_prints_a_verifier_line(monkeypatch, capsys):
    answers = iter([PASSWORD, PASSWORD])
    monkeypatch.setattr(provision.getpass, "getpass", lambda prompt: next(answers))
    assert provision.main(["set-operator-password"]) == 0
    output = capsys.readouterr().out
    assert f"{OPERATOR_VERIFIER_ENV}=scrypt$" in output
    assert PASSWORD not in output
    line = next(line for line in output.splitlines() if line.startswith(OPERATOR_VERIFIER_ENV + "="))
    assert verify_password(PASSWORD, line.split("=", 1)[1])


def test_provisioning_rejects_mismatched_passwords(monkeypatch, capsys):
    answers = iter([PASSWORD, "different-password-value"])
    monkeypatch.setattr(provision.getpass, "getpass", lambda prompt: next(answers))
    assert provision.main(["set-operator-password"]) == 1
    assert OPERATOR_VERIFIER_ENV not in capsys.readouterr().out


def test_provisioning_rejects_short_passwords(monkeypatch, capsys):
    answers = iter(["short", "short"])
    monkeypatch.setattr(provision.getpass, "getpass", lambda prompt: next(answers))
    assert provision.main(["set-operator-password"]) == 1
    assert "12" in capsys.readouterr().err
