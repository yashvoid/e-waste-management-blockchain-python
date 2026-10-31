import json
from pathlib import Path

import pytest

from app.crypto.canonical import canonical_bytes, canonical_text
from app.crypto.hexutil import bytes_to_hex, hex_to_bytes
from app.crypto.secp256k1 import (
    ADDRESS_TAG,
    TRANSACTION_TAG,
    domain_hash,
    sha256,
    verify_digest,
    wallet_address_from_public_key,
)
from app.crypto.strict_json import parse_strict_json_bytes

TRANSACTION_PAYLOAD_LIMIT = 16 * 1024

VECTORS = json.loads(
    (Path(__file__).resolve().parents[2] / "test-vectors" / "crypto-vectors.json").read_text(encoding="utf-8")
)


def canonicalize_text(text: str) -> str:
    return canonical_text(parse_strict_json_bytes(text.encode("utf-8"), TRANSACTION_PAYLOAD_LIMIT))


@pytest.mark.parametrize("vector", VECTORS["canonical_valid"], ids=lambda v: v["name"])
def test_canonical_matches_shared_vector(vector):
    assert canonicalize_text(vector["input_text"]) == vector["canonical_text"]
    parsed = parse_strict_json_bytes(vector["input_text"].encode("utf-8"), TRANSACTION_PAYLOAD_LIMIT)
    assert bytes_to_hex(canonical_bytes(parsed)) == vector[
        "canonical_hex"
    ]


@pytest.mark.parametrize("vector", VECTORS["canonical_invalid"], ids=lambda v: v["name"])
def test_strict_parse_and_canonical_reject(vector):
    with pytest.raises((ValueError, UnicodeError)):
        canonicalize_text(vector["input"])


def test_canonical_rejects_non_string_key_built_in_code():
    with pytest.raises(ValueError):
        canonical_text({1: "a"})


@pytest.mark.parametrize("value", [None, 1, b"ab"])
def test_hex_rejects_non_string_input(value):
    with pytest.raises(ValueError):
        hex_to_bytes(value)


def test_canonical_rejects_non_nfc_string_built_in_code():
    with pytest.raises(ValueError):
        canonical_text({"a": "e\u0301"})


def test_canonical_rejects_lone_surrogate_built_in_code():
    with pytest.raises(ValueError):
        canonical_text({"a": "\ud800"})


@pytest.mark.parametrize("value", [2**53, -(2**53), 1.5, object()])
def test_canonical_rejects_unsupported_values_built_in_code(value):
    with pytest.raises(ValueError):
        canonical_text({"a": value})


@pytest.mark.parametrize("vector", VECTORS["sha256"], ids=lambda v: v["input_hex"] or "empty")
def test_sha256_matches_vector(vector):
    assert bytes_to_hex(sha256(hex_to_bytes(vector["input_hex"]))) == vector["output_hex"]


@pytest.mark.parametrize("vector", VECTORS["domain_hash"], ids=lambda v: v["tag"])
def test_domain_hash_matches_vector(vector):
    assert bytes_to_hex(domain_hash(vector["tag"], hex_to_bytes(vector["payload_hex"]))) == vector["output_hex"]


def test_domain_tags_produce_different_digests_for_the_same_payload():
    assert domain_hash(TRANSACTION_TAG, b"\x00") != domain_hash(ADDRESS_TAG, b"\x00")


@pytest.mark.parametrize("vector", VECTORS["addresses"], ids=lambda v: v["name"])
def test_wallet_address_matches_vector(vector):
    assert wallet_address_from_public_key(vector["public_key_hex"]) == vector["address_hex"]


@pytest.mark.parametrize("vector", VECTORS["signatures"], ids=lambda v: v["name"])
def test_signature_verification_matches_vector(vector):
    assert (
        verify_digest(vector["public_key_hex"], hex_to_bytes(vector["digest_hex"]), vector["signature_hex"])
        is vector["expected_valid"]
    )


def test_transaction_digest_recomputes_from_canonical_body():
    transaction = VECTORS["transaction"]
    parsed = parse_strict_json_bytes(transaction["canonical_text"].encode(), TRANSACTION_PAYLOAD_LIMIT)
    digest = domain_hash(TRANSACTION_TAG, canonical_bytes(parsed))
    assert bytes_to_hex(digest) == transaction["digest_hex"]


def test_altered_transaction_body_fails_verification():
    transaction = VECTORS["transaction"]
    parsed = parse_strict_json_bytes(transaction["altered_canonical_text"].encode(), TRANSACTION_PAYLOAD_LIMIT)
    altered = domain_hash(TRANSACTION_TAG, canonical_bytes(parsed))
    valid_key = next(entry["public_key_hex"] for entry in VECTORS["signatures"] if entry["expected_valid"])
    assert bytes_to_hex(altered) == transaction["altered_digest_hex"]
    assert verify_digest(valid_key, altered, transaction["signature_hex"]) is False
