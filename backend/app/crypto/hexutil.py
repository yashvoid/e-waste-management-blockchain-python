import re

_HEX_PATTERN = re.compile(r"(?:[0-9a-f]{2})*")


def bytes_to_hex(data: bytes) -> str:
    return data.hex()


def hex_to_bytes(text: str, expected_length: int | None = None) -> bytes:
    if not isinstance(text, str) or _HEX_PATTERN.fullmatch(text) is None:
        raise ValueError("Invalid hex: must be lowercase and even length.")
    data = bytes.fromhex(text)
    if expected_length is not None and len(data) != expected_length:
        raise ValueError(f"Invalid hex length: expected {expected_length} bytes.")
    return data
