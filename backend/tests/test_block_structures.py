import dataclasses
import json
from pathlib import Path

import pytest

from app.blockchain.structures import (
    GENESIS_PREVIOUS_HASH,
    block_work,
    compute_transaction_root,
    make_block,
    make_genesis_block,
    make_transaction,
    meets_proof_of_work,
    parse_utc_timestamp,
    transaction_body,
    transaction_digest,
)
from chain_helpers import key_for_label, shared_network_config, sign_transaction

VECTORS = json.loads(
    (Path(__file__).resolve().parents[2] / "test-vectors" / "crypto-vectors.json").read_text(encoding="utf-8")
)
TIMESTAMP = "2026-01-01T00:00:10Z"


def test_transaction_id_is_deterministic_and_matches_signed_body() -> None:
    config = shared_network_config()
    first = sign_transaction(config, key_for_label("alice"), TIMESTAMP)
    second = sign_transaction(config, key_for_label("alice"), TIMESTAMP)

    body = transaction_body(
        config.network_id,
        config.protocol_version,
        TIMESTAMP,
        first.sender_public_key,
        "test-event",
        {"reference": "test"},
        0,
    )
    assert first.txid == second.txid == transaction_digest(body).hex()


def test_transaction_id_changes_with_signed_content_but_not_with_signature() -> None:
    config = shared_network_config()
    original = sign_transaction(config, key_for_label("alice"), TIMESTAMP)
    other_payload = sign_transaction(config, key_for_label("alice"), TIMESTAMP, payload={"reference": "other"})

    assert original.txid != other_payload.txid

    resigned = make_transaction(
        original.network_id,
        original.protocol_version,
        original.timestamp,
        original.sender_public_key,
        original.tx_type,
        original.payload,
        original.nonce,
        signature="00" * 64,
    )
    assert resigned.txid == original.txid


def test_block_hash_is_deterministic_and_depends_on_header() -> None:
    config = shared_network_config()
    genesis = make_genesis_block(config.network_id, config.protocol_version, "2026-01-01T00:00:00Z", 1, 0)
    args = dict(
        network_id=config.network_id,
        protocol_version=config.protocol_version,
        height=1,
        previous_hash=genesis.block_hash,
        timestamp=TIMESTAMP,
        difficulty=1,
        transactions=[],
    )

    assert make_block(nonce=5, **args).block_hash == make_block(nonce=5, **args).block_hash
    assert make_block(nonce=5, **args).block_hash != make_block(nonce=6, **args).block_hash
    assert make_block(nonce=5, **dict(args, network_id="other-network")).block_hash != (
        make_block(nonce=5, **args).block_hash
    )


def test_genesis_is_deterministic_with_zero_previous_hash() -> None:
    first = make_genesis_block("test-network", 1, "2026-01-01T00:00:00Z", 1, 0)
    second = make_genesis_block("test-network", 1, "2026-01-01T00:00:00Z", 1, 0)

    assert first == second
    assert first.height == 0
    assert first.previous_hash == GENESIS_PREVIOUS_HASH
    assert first.transactions == ()


@pytest.mark.parametrize("vector", VECTORS["transaction_root"], ids=lambda v: v["name"])
def test_transaction_root_matches_shared_vector(vector: dict) -> None:
    leaves = [(entry["txid"], entry["signature"]) for entry in vector["transactions"]]
    assert compute_transaction_root(leaves) == vector["output_hex"]


def test_transaction_root_depends_on_order() -> None:
    leaves = [(entry["txid"], entry["signature"]) for entry in VECTORS["transaction_root"][1]["transactions"]]
    assert compute_transaction_root(leaves) != compute_transaction_root(list(reversed(leaves)))


def test_block_hash_commits_to_transaction_signatures() -> None:
    config = shared_network_config()
    signed = sign_transaction(config, key_for_label("alice"), TIMESTAMP)
    altered = dataclasses.replace(signed, signature=VECTORS["signatures"][4]["signature_hex"])
    assert altered.txid == signed.txid

    original_block = make_block(config.network_id, config.protocol_version, 1, GENESIS_PREVIOUS_HASH, TIMESTAMP, 1, 0, [signed])
    altered_block = make_block(config.network_id, config.protocol_version, 1, GENESIS_PREVIOUS_HASH, TIMESTAMP, 1, 0, [altered])

    assert altered_block.transaction_root != original_block.transaction_root
    assert altered_block.block_hash != original_block.block_hash


def test_proof_of_work_boundary_is_strictly_below_target() -> None:
    difficulty = 8
    target = 1 << (256 - difficulty)

    assert meets_proof_of_work(format(target - 1, "064x"), difficulty)
    assert not meets_proof_of_work(format(target, "064x"), difficulty)
    assert not meets_proof_of_work("ff" * 32, difficulty)


def test_block_work_is_two_to_the_difficulty() -> None:
    genesis = make_genesis_block("test-network", 1, "2026-01-01T00:00:00Z", 1, 0)
    block = make_block("test-network", 1, 1, genesis.block_hash, TIMESTAMP, 9, 0, [])

    assert block_work(block) == 512


@pytest.mark.parametrize(
    "text",
    ["2026-01-01T00:00:00+00:00", "2026-01-01 00:00:00Z", "2026-01-01T00:00Z", "2026-02-30T00:00:00Z", 1767225600],
)
def test_invalid_timestamp_text_is_rejected(text: object) -> None:
    with pytest.raises(ValueError):
        parse_utc_timestamp(text)


def test_valid_timestamp_parses_as_utc() -> None:
    parsed = parse_utc_timestamp("2026-01-01T12:30:45Z")

    assert parsed.utcoffset().total_seconds() == 0
    assert parsed.second == 45
