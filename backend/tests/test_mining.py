import dataclasses
import threading

import pytest

from app.blockchain.mining import add_block, mine_block, open_chain
from app.blockchain.structures import BlockStore, make_genesis_block, meets_proof_of_work
from app.blockchain.validation import ValidationError
from chain_helpers import (
    TEST_GENESIS_TIMESTAMP,
    key_for_label,
    mine,
    mine_and_add,
    shared_network_config,
    sign_transaction,
)

GENESIS_TIME = "2026-01-01T00:00:00Z"
C1_TIME = "2026-01-01T00:00:10Z"
A2_TIME = "2026-01-01T00:00:20Z"
A3_TIME = "2026-01-01T00:00:30Z"
B2_TIME = "2026-01-01T00:00:21Z"
B3_TIME = "2026-01-01T00:00:31Z"
B4_TIME = "2026-01-01T00:00:41Z"


@pytest.fixture
def config():
    return shared_network_config(difficulty=1)


def tx(config, label: str, timestamp: str):
    return sign_transaction(config, key_for_label(label), timestamp, payload={"reference": label})


def find_block_by_hash_order(config, parent, timestamp, reference_hash: str, want_smaller: bool):
    for index in range(10_000):
        block = mine(config, parent, [tx(config, f"search-{index}", timestamp)], timestamp)
        if (block.block_hash < reference_hash) == want_smaller:
            return block
    raise AssertionError("No candidate block with the required hash order was found.")


def test_mined_block_meets_target_and_extends_chain(config) -> None:
    store = open_chain(config)
    block, update = mine_and_add(store, config, store.tip, [tx(config, "alice", C1_TIME)], C1_TIME)

    assert meets_proof_of_work(block.block_hash, config.initial_difficulty)
    assert update.canonical_changed
    assert store.tip == block
    assert store.cumulative_work(store.tip) == 2
    assert store.ancestry(store.tip)[-1] == store.canonical_chain[0]


def test_mining_returns_none_when_cancelled_before_start(config) -> None:
    cancel = threading.Event()
    cancel.set()

    assert mine_block(config, open_chain(config).tip, [], C1_TIME, cancel) is None


def test_mining_stops_when_cancelled_during_search() -> None:
    hard_config = dataclasses.replace(shared_network_config(difficulty=1), initial_difficulty=32)
    store = BlockStore(make_genesis_block(hard_config.network_id, hard_config.protocol_version, TEST_GENESIS_TIMESTAMP, 32, 0))
    cancel = threading.Event()
    timer = threading.Timer(0.05, cancel.set)
    timer.start()
    try:
        result = mine_block(hard_config, store.tip, [], C1_TIME, cancel)
    finally:
        timer.cancel()

    assert result is None


def test_duplicate_block_is_ignored(config) -> None:
    store = open_chain(config)
    block, _ = mine_and_add(store, config, store.tip, [], C1_TIME)

    update = add_block(store, config, block)

    assert not update.canonical_changed
    assert len(store.blocks_by_hash) == 2


def test_invalid_block_leaves_store_unchanged(config) -> None:
    store = open_chain(config)
    block, _ = mine_and_add(store, config, store.tip, [], C1_TIME)
    tip_before = store.tip
    bad = dataclasses.replace(block, nonce=block.nonce + 1)

    with pytest.raises(ValidationError):
        add_block(store, config, bad)
    assert store.tip == tip_before
    assert len(store.blocks_by_hash) == 2


def test_lower_work_side_branch_is_retained_without_changing_canonical(config) -> None:
    store = open_chain(config)
    _, _ = mine_and_add(store, config, store.tip, [], C1_TIME)
    _, _ = mine_and_add(store, config, store.tip, [], A2_TIME)
    genesis = store.canonical_chain[0]
    tip_before = store.tip

    side, update = mine_and_add(store, config, genesis, [tx(config, "side", B2_TIME)], B2_TIME)

    assert not update.canonical_changed
    assert store.tip == tip_before
    assert store.blocks_by_hash[side.block_hash] == side


def test_equal_work_tie_is_won_by_smaller_tip_hash(config) -> None:
    probe = open_chain(config)
    x = mine(config, probe.tip, [tx(config, "x", C1_TIME)], C1_TIME)
    y = mine(config, probe.tip, [tx(config, "y", C1_TIME)], C1_TIME)
    expected_winner = min(x.block_hash, y.block_hash)

    for first, second in [(x, y), (y, x)]:
        store = open_chain(config)
        add_block(store, config, first)
        add_block(store, config, second)

        assert store.tip.block_hash == expected_winner
        assert store.cumulative_work(store.tip) == 2


def test_same_transaction_on_competing_branch_is_not_rejected(config) -> None:
    shared = tx(config, "shared", C1_TIME)
    store = open_chain(config)
    _, _ = mine_and_add(store, config, store.tip, [shared], C1_TIME)
    _, _ = mine_and_add(store, config, store.tip, [], A2_TIME)
    genesis = store.canonical_chain[0]

    _, update = mine_and_add(store, config, genesis, [shared], B2_TIME)

    assert not update.canonical_changed
    assert len(store.blocks_by_hash) == 4


@pytest.mark.parametrize("side_wins_tie", [True, False])
def test_reorganization_reports_removed_and_newly_confirmed_transactions(config, side_wins_tie: bool) -> None:
    store = open_chain(config)
    genesis = store.canonical_chain[0]
    common_tx = tx(config, "common", C1_TIME)
    _, _ = mine_and_add(store, config, genesis, [common_tx], C1_TIME)
    c1 = store.tip

    a2_tx = tx(config, "a2", A2_TIME)
    a3_tx = tx(config, "a3", A3_TIME)
    _, _ = mine_and_add(store, config, c1, [a2_tx], A2_TIME)
    a2 = store.tip
    a3, _ = mine_and_add(store, config, a2, [a3_tx], A3_TIME)
    assert store.tip == a3

    b2_tx = tx(config, "b2", B2_TIME)
    b2, update_b2 = mine_and_add(store, config, c1, [b2_tx], B2_TIME)
    assert not update_b2.canonical_changed

    b3 = find_block_by_hash_order(config, b2, B3_TIME, a3.block_hash, want_smaller=side_wins_tie)
    update_b3 = add_block(store, config, b3)

    b4_tx = tx(config, "b4", B4_TIME)
    b4 = mine(config, b3, [b4_tx], B4_TIME)
    update_b4 = add_block(store, config, b4)

    assert store.tip == b4
    a_txs = sorted([a2_tx, a3_tx], key=lambda t: (t.timestamp, t.txid))
    b_txs = sorted([b2_tx, b3.transactions[0]], key=lambda t: (t.timestamp, t.txid))

    if side_wins_tie:
        assert update_b3.canonical_changed
        assert update_b3.removed_transactions == tuple(a_txs)
        assert update_b3.newly_confirmed_transactions == tuple(b_txs)
        assert update_b4.removed_transactions == ()
        assert update_b4.newly_confirmed_transactions == (b4_tx,)
    else:
        assert not update_b3.canonical_changed
        assert update_b4.canonical_changed
        assert update_b4.removed_transactions == tuple(a_txs)
        expected = tuple(sorted(b_txs + [b4_tx], key=lambda t: (t.timestamp, t.txid)))
        assert update_b4.newly_confirmed_transactions == expected

    reported = {t.txid for t in update_b3.removed_transactions + update_b3.newly_confirmed_transactions}
    reported |= {t.txid for t in update_b4.removed_transactions + update_b4.newly_confirmed_transactions}
    assert common_tx.txid not in reported


def test_transaction_on_both_complete_branches_is_not_reported(config) -> None:
    store = open_chain(config)
    genesis = store.canonical_chain[0]
    shared = tx(config, "shared", A2_TIME)
    a2_only = tx(config, "a2-only", A3_TIME)
    a2, _ = mine_and_add(store, config, genesis, [shared], A2_TIME)
    mine_and_add(store, config, a2, [a2_only], A3_TIME)

    b2, _ = mine_and_add(store, config, genesis, [shared], B2_TIME)
    b3 = find_block_by_hash_order(config, b2, B3_TIME, store.tip.block_hash, want_smaller=False)
    assert not add_block(store, config, b3).canonical_changed

    b4_tx = tx(config, "b4", B4_TIME)
    b4 = mine(config, b3, [b4_tx], B4_TIME)
    update = add_block(store, config, b4)

    assert store.tip == b4
    assert update.removed_transactions == (a2_only,)
    expected = tuple(sorted([b3.transactions[0], b4_tx], key=lambda t: (t.timestamp, t.txid)))
    assert update.newly_confirmed_transactions == expected
    assert shared.txid not in {t.txid for t in update.removed_transactions + update.newly_confirmed_transactions}


def test_cumulative_work_counts_every_non_genesis_block(config) -> None:
    store = open_chain(config)
    tip = store.tip
    for index in range(5):
        tip, _ = mine_and_add(store, config, tip, [], f"2026-01-01T00:00:{10 + index:02d}Z")
    tip = store.tip

    assert store.cumulative_work(tip) == 5 * (1 << config.initial_difficulty)
