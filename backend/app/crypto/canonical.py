import unicodedata
from typing import Any

MAX_DEPTH = 32
MAX_SAFE_INTEGER = 2**53 - 1


def canonical_text(value: Any) -> str:
    return _encode(value, 0)


def canonical_bytes(value: Any) -> bytes:
    return canonical_text(value).encode("utf-8")


def _encode(value: Any, depth: int) -> str:
    if isinstance(value, str):
        return _encode_string(value)
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if type(value) is int:
        if abs(value) > MAX_SAFE_INTEGER:
            raise ValueError("Canonical integers must be within the safe range.")
        return str(value)
    if isinstance(value, list):
        _check_depth(depth + 1)
        return "[" + ",".join(_encode(item, depth + 1) for item in value) + "]"
    if type(value) is dict:
        _check_depth(depth + 1)
        for key in value:
            if not isinstance(key, str):
                raise ValueError("Object keys must be strings.")
        encoded_keys = {key: _encode_string(key) for key in value}
        ordered_keys = sorted(value, key=lambda key: key.encode("utf-8"))
        members = [f"{encoded_keys[key]}:{_encode(value[key], depth + 1)}" for key in ordered_keys]
        return "{" + ",".join(members) + "}"
    raise ValueError("Unsupported value in canonical serialization.")


def _encode_string(text: str) -> str:
    for char in text:
        if "\ud800" <= char <= "\udfff":
            raise ValueError("Strings must not contain lone surrogates.")
    if unicodedata.normalize("NFC", text) != text:
        raise ValueError("Strings must be Unicode NFC normalized.")
    out = ['"']
    for char in text:
        code = ord(char)
        if char == '"':
            out.append('\\"')
        elif char == "\\":
            out.append("\\\\")
        elif code < 0x20:
            out.append(f"\\u{code:04x}")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def _check_depth(depth: int) -> None:
    if depth > MAX_DEPTH:
        raise ValueError("Nesting depth exceeds the limit.")
