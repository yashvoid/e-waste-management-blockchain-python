import hashlib
import hmac
import secrets

SCHEME = "scrypt"
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_MAX_N = 2**20
SALT_BYTES = 16
DIGEST_BYTES = 32
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 256
_MAX_MEMORY_BYTES = 64 * 1024 * 1024


def make_verifier(password: str) -> str:
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise ValueError(
            f"The operator password must be {MIN_PASSWORD_LENGTH} to {MAX_PASSWORD_LENGTH} characters long."
        )
    salt = secrets.token_bytes(SALT_BYTES)
    digest = _derive(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P, DIGEST_BYTES)
    return f"{SCHEME}${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def validate_verifier(verifier: str) -> None:
    _parse(verifier)


def verify_password(password: str, verifier: str) -> bool:
    n, r, p, salt, expected = _parse(verifier)
    actual = _derive(password, salt, n, r, p, len(expected))
    return hmac.compare_digest(actual, expected)


def _parse(verifier: str) -> tuple[int, int, int, bytes, bytes]:
    parts = verifier.split("$")
    if len(parts) != 6 or parts[0] != SCHEME:
        raise ValueError("The operator password verifier is malformed.")
    try:
        n, r, p = int(parts[1]), int(parts[2]), int(parts[3])
        salt = bytes.fromhex(parts[4])
        expected = bytes.fromhex(parts[5])
    except ValueError as exc:
        raise ValueError("The operator password verifier is malformed.") from exc
    if not (SCRYPT_N <= n <= SCRYPT_MAX_N and n & (n - 1) == 0) or r < 1 or p < 1:
        raise ValueError("The operator password verifier is malformed.")
    if len(salt) < SALT_BYTES or len(expected) < DIGEST_BYTES:
        raise ValueError("The operator password verifier is malformed.")
    return n, r, p, salt, expected


def _derive(password: str, salt: bytes, n: int, r: int, p: int, length: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=length,
        maxmem=_MAX_MEMORY_BYTES,
    )
