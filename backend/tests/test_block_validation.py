import dataclasses

import pytest
from coincurve import PrivateKey

from app.blockchain.mining import add_block, open_chain
from app.blockchain.structures import make_block, make_genesis_block, make_transaction, meets_proof_of_work
from app.blockchain.validation import ValidationError, validate_block, verify_genesis
from app.crypto.canonical import canonical_bytes
from chain_helpers import key_for_label, mine, mine_and_add, shared_network_config, sign_transaction

TIMESTAMP = "2026-01-01T00:00:10Z"
LATER_TIMESTAMP = "2026-01-01T00:00:20Z"


@pytest.fixture
def config():
    return shared_network_config(difficulty=1)


@pytest.fixture
def store(config):
    return open_chain(config)


def test_valid_block_with_signed_transaction_is_accepted(config, store) -> None:
    transaction = sign_transaction(config, key_for_label("alice"), TIMESTAMP)

    _, update = mine_and_add(store, config, store.tip, [transaction], TIMESTAMP)

    assert update.canonical_changed
    assert store.tip.transactions == (transaction,)


def test_transaction_with_another_keys_signature_is_rejected(config, store) -> None:
    alice = sign_transaction(config, key_for_label("alice"), TIMESTAMP)
    bob = sign_transaction(config, key_for_label("bob"), TIMESTAMP, payload={"reference": "bob"})
    forged = make_transaction(
        alice.network_id,
        alice.protocol_version,
        alice.timestamp,
        alice.sender_public_key,
        alice.tx_type,
        alice.payload,
        alice.nonce,
        signature=bob.signature,
    )
    block = mine(config, store.tip, [forged], TIMESTAMP)

    with pytest.raises(ValidationError, match="signature"):
        add_block(store, config, block)
    assert len(store.blocks_by_hash) == 1


def test_transaction_claiming_another_sender_is_rejected(config, store) -> None:
    alice = sign_transaction(config, key_for_label("alice"), TIMESTAMP)
    bob_public_key = PrivateKey(key_for_label("bob")).public_key.format(compressed=True).hex()
    forged = make_transaction(
        alice.network_id,
        alice.protocol_version,
        alice.timestamp,
        bob_public_key,
        alice.tx_type,
        alice.payload,
        alice.nonce,
        signature=alice.signature,
    )
    block = mine(config, store.tip, [forged], TIMESTAMP)

    with pytest.raises(ValidationError, match="signature"):
        add_block(store, config, block)


def test_transaction_with_tampered_content_is_rejected(config, store) -> None:
    transaction = sign_transaction(config, key_for_label("alice"), TIMESTAMP)
    tampered = dataclasses.replace(transaction, payload={"reference": "changed"})
    block = mine(config, store.tip, [tampered], TIMESTAMP)

    with pytest.raises(ValidationError, match="transaction ID"):
        add_block(store, config, block)


def test_transaction_from_another_network_is_rejected(config, store) -> None:
    other = dataclasses.replace(config, network_id="other-network")
    transaction = sign_transaction(other, key_for_label("alice"), TIMESTAMP)
    block = mine(config, store.tip, [transaction], TIMESTAMP)

    with pytest.raises(ValidationError, match="different network"):
        add_block(store, config, block)


def test_oversized_transaction_payload_is_rejected(config, store) -> None:
    small = dataclasses.replace(config, max_transaction_payload_bytes=32)
    transaction = sign_transaction(config, key_for_label("alice"), TIMESTAMP, payload={"reference": "x" * 64})
    block = mine(config, store.tip, [transaction], TIMESTAMP)

    with pytest.raises(ValidationError, match="payload exceeds"):
        validate_block(block, small, store.ancestry(store.tip))


def test_block_size_limit_is_inclusive(config, store) -> None:
    transaction = sign_transaction(config, key_for_label("alice"), TIMESTAMP)
    block = mine(config, store.tip, [transaction], TIMESTAMP)
    size = len(canonical_bytes(block.to_dict()))
    ancestors = store.ancestry(store.tip)

    validate_block(block, dataclasses.replace(config, max_block_size_bytes=size), ancestors)
    with pytest.raises(ValidationError, match="maximum allowed size"):
        validate_block(block, dataclasses.replace(config, max_block_size_bytes=size - 1), ancestors)


def test_block_with_too_many_transactions_is_rejected(config, store) -> None:
    limited = dataclasses.replace(config, max_transactions_per_block=1)
    first = sign_transaction(config, key_for_label("alice"), TIMESTAMP)
    second = sign_transaction(config, key_for_label("bob"), TIMESTAMP)
    block = mine(config, store.tip, [first, second], TIMESTAMP)

    with pytest.raises(ValidationError, match="more transactions"):
        validate_block(block, limited, store.ancestry(store.tip))


def test_same_transaction_twice_in_one_block_is_rejected(config, store) -> None:
    transaction = sign_transaction(config, key_for_label("alice"), TIMESTAMP)
    block = make_block(
        config.network_id,
        config.protocol_version,
        1,
        store.tip.block_hash,
        TIMESTAMP,
        config.initial_difficulty,
        0,
        [transaction, transaction],
    )

    with pytest.raises(ValidationError, match="more than once"):
        validate_block(block, config, store.ancestry(store.tip))


def test_transaction_repeated_from_ancestry_is_rejected(config, store) -> None:
    transaction = sign_transaction(config, key_for_label("alice"), TIMESTAMP)
    first, _ = mine_and_add(store, config, store.tip, [transaction], TIMESTAMP)
    block = mine(config, first, [transaction], LATER_TIMESTAMP)

    with pytest.raises(ValidationError, match="ancestry"):
        add_block(store, config, block)
    assert len(store.blocks_by_hash) == 2


def test_transactions_out_of_timestamp_and_id_order_are_rejected(config, store) -> None:
    early = sign_transaction(config, key_for_label("alice"), TIMESTAMP)
    late = sign_transaction(config, key_for_label("bob"), LATER_TIMESTAMP)
    block = make_block(
        config.network_id,
        config.protocol_version,
        1,
        store.tip.block_hash,
        TIMESTAMP,
        config.initial_difficulty,
        0,
        [late, early],
    )

    with pytest.raises(ValidationError, match="order"):
        validate_block(block, config, store.ancestry(store.tip))


def test_block_timestamp_equal_to_parent_is_rejected(config, store) -> None:
    block = mine(config, store.tip, [], store.tip.timestamp)

    with pytest.raises(ValidationError, match="later than its parent"):
        add_block(store, config, block)


def test_block_timestamp_two_hours_ahead_is_accepted_and_beyond_is_rejected(config, store) -> None:
    beyond = mine(config, store.tip, [], "2026-01-01T02:00:01Z")
    with pytest.raises(ValidationError, match="too far ahead"):
        add_block(store, config, beyond)

    boundary = mine(config, store.tip, [], "2026-01-01T02:00:00Z")
    assert add_block(store, config, boundary).canonical_changed


def test_malformed_block_timestamp_is_rejected(config, store) -> None:
    block = mine(config, store.tip, [], "2026-01-01T00:00:30+00:00")

    with pytest.raises(ValidationError, match="UTC timestamp"):
        add_block(store, config, block)


def test_block_below_proof_of_work_target_is_rejected() -> None:
    difficulty = 8
    config = shared_network_config(difficulty=difficulty)
    store = open_chain(config)
    nonce = 0
    while True:
        block = make_block(
            config.network_id,
            config.protocol_version,
            1,
            store.tip.block_hash,
            TIMESTAMP,
            difficulty,
            nonce,
            [],
        )
        if not meets_proof_of_work(block.block_hash, difficulty):
            break
        nonce += 1

    with pytest.raises(ValidationError, match="proof-of-work"):
        add_block(store, config, block)


def test_block_with_different_difficulty_is_rejected(config, store) -> None:
    block = make_block(
        config.network_id,
        config.protocol_version,
        1,
        store.tip.block_hash,
        TIMESTAMP,
        2,
        0,
        [],
    )

    with pytest.raises(ValidationError, match="difficulty"):
        add_block(store, config, block)


def test_block_with_wrong_height_is_rejected(config, store) -> None:
    block = make_block(
        config.network_id,
        config.protocol_version,
        2,
        store.tip.block_hash,
        TIMESTAMP,
        config.initial_difficulty,
        0,
        [],
    )

    with pytest.raises(ValidationError, match="height"):
        validate_block(block, config, store.ancestry(store.tip))


def test_block_with_unknown_parent_is_rejected(config, store) -> None:
    block = make_block(
        config.network_id,
        config.protocol_version,
        1,
        "ab" * 32,
        TIMESTAMP,
        config.initial_difficulty,
        0,
        [],
    )

    with pytest.raises(ValidationError, match="parent"):
        add_block(store, config, block)
    assert len(store.blocks_by_hash) == 1


def test_genesis_matches_shared_configuration(config) -> None:
    genesis = verify_genesis(config)

    assert genesis.height == 0
    assert genesis.block_hash == config.genesis_hash


def test_genesis_hash_mismatch_is_rejected(config) -> None:
    wrong = dataclasses.replace(config, genesis_hash="00" * 32)

    with pytest.raises(ValidationError, match="genesis hash"):
        open_chain(wrong)


def test_genesis_timestamp_change_is_rejected(config) -> None:
    changed = dataclasses.replace(config, genesis_timestamp="2026-01-01T00:00:01Z")

    with pytest.raises(ValidationError, match="genesis hash"):
        open_chain(changed)


def test_genesis_failing_proof_of_work_is_rejected(config) -> None:
    genesis = make_genesis_block(config.network_id, config.protocol_version, config.genesis_timestamp, 32, config.genesis_nonce)
    unmined = dataclasses.replace(config, initial_difficulty=32, genesis_hash=genesis.block_hash)

    with pytest.raises(ValidationError, match="proof-of-work"):
        open_chain(unmined)
