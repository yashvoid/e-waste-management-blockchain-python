import pytest

from app.crypto.strict_json import parse_strict_json_bytes


def test_rejects_input_over_byte_limit():
    data = b"[" + b" " * 16 + b"]"
    with pytest.raises(ValueError):
        parse_strict_json_bytes(data, len(data) - 1)


def test_accepts_input_exactly_at_byte_limit():
    data = b"[" + b" " * 16 + b"]"
    assert parse_strict_json_bytes(data, len(data)) == []


def test_accepts_nesting_depth_32():
    data = b"[" * 32 + b"]" * 32
    assert parse_strict_json_bytes(data, 1024) is not None


def test_rejects_nesting_depth_33():
    data = b"[" * 33 + b"]" * 33
    with pytest.raises(ValueError):
        parse_strict_json_bytes(data, 1024)


def test_deep_nesting_raises_value_error_not_recursion_error():
    data = b"[" * 100_000 + b"]" * 100_000
    with pytest.raises(ValueError):
        parse_strict_json_bytes(data, len(data))


def test_brackets_inside_strings_do_not_count_toward_depth():
    data = b'["' + b"[" * 40 + b'"]'
    assert parse_strict_json_bytes(data, len(data)) == ["[" * 40]


def test_rejects_invalid_utf8():
    with pytest.raises(ValueError):
        parse_strict_json_bytes(b'["\xff"]', 64)


def test_rejects_duplicate_keys():
    with pytest.raises(ValueError):
        parse_strict_json_bytes(b'{"a":1,"a":2}', 64)
