import json
from typing import Any

from app.crypto.canonical import MAX_DEPTH, MAX_SAFE_INTEGER


def parse_strict_json_bytes(data: bytes, max_bytes: int) -> Any:
    if len(data) > max_bytes:
        raise ValueError("Input exceeds the maximum allowed size.")
    text = data.decode("utf-8")
    _reject_excessive_depth(text)
    return json.loads(
        text,
        object_pairs_hook=_reject_duplicate_keys,
        parse_int=_parse_safe_integer,
        parse_float=_reject_number,
        parse_constant=_reject_constant,
    )


def _reject_excessive_depth(text: str) -> None:
    depth = 0
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
            if depth > MAX_DEPTH:
                raise ValueError("Nesting depth exceeds the limit.")
        elif char in "]}":
            depth -= 1


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate object key.")
        result[key] = value
    return result


def _parse_safe_integer(token: str) -> int:
    if token == "-0":
        raise ValueError("Negative zero is not allowed.")
    value = int(token)
    if abs(value) > MAX_SAFE_INTEGER:
        raise ValueError("Integer is outside the safe range.")
    return value


def _reject_number(token: str) -> None:
    raise ValueError("Only integers are allowed.")


def _reject_constant(token: str) -> None:
    raise ValueError("NaN and Infinity are not allowed.")
