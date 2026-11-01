import dataclasses
from pathlib import Path

from app.node.pending_pool import PendingTransactionPool
from app.storage.chain_storage import open_chain_storage
from chain_helpers import key_for_label, mine, shared_network_config, sign_transaction

CONFIG = shared_network_config()


def _ts(index: int) -> str:
    return f"2026-01-01T{index // 60:02d}:{index % 60:02d}:00Z"


def _tx(label: str, index: int, **kwargs):
    return sign_transaction(CONFIG, key_for_label(label), _ts(index), **kwargs)


def test_valid_signed_transaction_is_admitted(tmp_path: Path) -> None:
    tx = _tx("alice", 1, payload={"n": 1})
    with open_chain_storage(tmp_path / "data", CONFIG) as storage:
        pool = PendingTransactionPool(storage)
        result = pool.admit(tx)
        assert result.state == "accepted"
        assert pool.get(tx.txid) == tx


def test_invalid_signature_is_rejected(tmp_path: Path) -> None:
    tx = _tx("alice", 1)
    other = _tx("bob", 2)
    forged = dataclasses.replace(tx, signature=other.signature)
    with open_chain_storage(tmp_path / "data", CONFIG) as storage:
        pool = PendingTransactionPool(storage)
        assert pool.admit(forged).state == "rejected"
        assert pool.ordered() == ()


def test_incorrect_transaction_id_is_rejected(tmp_path: Path) -> None:
    tx = dataclasses.replace(_tx("alice", 1), txid="00" * 32)
    with open_chain_storage(tmp_path / "data", CONFIG) as storage:
        assert PendingTransactionPool(storage).admit(tx).state == "rejected"


def test_oversized_payload_is_rejected(tmp_path: Path) -> None:
    tx = _tx("alice", 1, payload={"blob": "a" * (CONFIG.max_transaction_payload_bytes + 1)})
    with open_chain_storage(tmp_path / "data", CONFIG) as storage:
        assert PendingTransactionPool(storage).admit(tx).state == "rejected"


def test_duplicate_transaction_is_reported_as_known(tmp_path: Path) -> None:
    tx = _tx("alice", 1)
    with open_chain_storage(tmp_path / "data", CONFIG) as storage:
        pool = PendingTransactionPool(storage)
        assert pool.admit(tx).state == "accepted"
        assert pool.admit(tx).state == "known"
        assert len(pool.ordered()) == 1


def test_confirmed_transaction_is_rejected(tmp_path: Path) -> None:
    tx = _tx("alice", 1)
    with open_chain_storage(tmp_path / "data", CONFIG) as storage:
        pool = PendingTransactionPool(storage)
        storage.add_block(mine(CONFIG, storage.store.tip, [tx], _ts(1)))
        assert pool.admit(tx).state == "confirmed"


def test_capacity_rejects_new_entries_without_evicting(tmp_path: Path) -> None:
    first, second, third = _tx("a", 1), _tx("b", 2), _tx("c", 3)
    with open_chain_storage(tmp_path / "data", CONFIG) as storage:
        pool = PendingTransactionPool(storage, capacity=2)
        assert pool.admit(first).state == "accepted"
        assert pool.admit(second).state == "accepted"
        assert pool.admit(third).state == "unavailable"
        assert {tx.txid for tx in pool.ordered()} == {first.txid, second.txid}


def test_ordering_is_by_timestamp_then_transaction_id(tmp_path: Path) -> None:
    late = _tx("a", 5)
    early = _tx("b", 2)
    same_time = _tx("c", 5)
    with open_chain_storage(tmp_path / "data", CONFIG) as storage:
        pool = PendingTransactionPool(storage)
        for tx in (late, same_time, early):
            pool.admit(tx)
        ordered = [tx.txid for tx in pool.ordered()]
        assert ordered[0] == early.txid
        assert ordered[1:] == sorted([late.txid, same_time.txid])
        assert [tx.txid for tx in pool.eligible_for_block(_ts(999))] == ordered


def test_pool_drops_transactions_confirmed_by_an_accepted_block(tmp_path: Path) -> None:
    tx = _tx("alice", 1)
    with open_chain_storage(tmp_path / "data", CONFIG) as storage:
        pool = PendingTransactionPool(storage)
        pool.admit(tx)
        storage.add_block(mine(CONFIG, storage.store.tip, [tx], _ts(1)))
        pool.reconcile([])
        assert pool.get(tx.txid) is None
        assert pool.ordered() == ()


def test_removed_transaction_is_readmitted_after_reorganization(tmp_path: Path) -> None:
    kept_tx = _tx("alice", 1)
    with open_chain_storage(tmp_path / "data", CONFIG) as storage:
        pool = PendingTransactionPool(storage)
        branch_a = mine(CONFIG, storage.store.tip, [kept_tx], _ts(1))
        storage.add_block(branch_a)
        branch_b1 = mine(CONFIG, storage.store.canonical_chain[0], [], _ts(1))
        first_update = storage.add_block(branch_b1)
        branch_b2 = mine(CONFIG, branch_b1, [], _ts(2))
        second_update = storage.add_block(branch_b2)
        removed = [*first_update.removed_transactions, *second_update.removed_transactions]
        assert kept_tx in removed
        pool.reconcile(removed)
        assert pool.get(kept_tx.txid) is not None


def test_transaction_on_non_canonical_branch_is_not_confirmed(tmp_path: Path) -> None:
    tx = _tx("alice", 1)
    with open_chain_storage(tmp_path / "data", CONFIG) as storage:
        pool = PendingTransactionPool(storage)
        heavy_1 = mine(CONFIG, storage.store.tip, [], _ts(1))
        storage.add_block(heavy_1)
        heavy_2 = mine(CONFIG, heavy_1, [], _ts(2))
        storage.add_block(heavy_2)
        light = mine(CONFIG, storage.store.canonical_chain[0], [tx], _ts(1))
        update = storage.add_block(light)
        assert not update.canonical_changed
        pool.reconcile([])
        assert pool.admit(tx).state == "accepted"


def test_pool_is_empty_after_restart_and_confirmed_transactions_stay_rejected(tmp_path: Path) -> None:
    pending = _tx("alice", 2)
    confirmed = _tx("bob", 1)
    data = tmp_path / "data"
    with open_chain_storage(data, CONFIG) as storage:
        PendingTransactionPool(storage).admit(pending)
        storage.add_block(mine(CONFIG, storage.store.tip, [confirmed], _ts(1)))
    with open_chain_storage(data, CONFIG) as storage:
        restarted = PendingTransactionPool(storage)
        assert restarted.ordered() == ()
        assert restarted.admit(confirmed).state == "confirmed"
        assert restarted.admit(pending).state == "accepted"


def test_block_selection_respects_transaction_count_limit(tmp_path: Path) -> None:
    limit = CONFIG.max_transactions_per_block
    txs = [_tx(f"user-{index}", index + 1) for index in range(limit + 3)]
    with open_chain_storage(tmp_path / "data", CONFIG) as storage:
        pool = PendingTransactionPool(storage, capacity=limit + 3)
        for tx in txs:
            pool.admit(tx)
        selected = pool.eligible_for_block(_ts(999))
        assert len(selected) == limit
        assert [tx.txid for tx in selected] == [tx.txid for tx in pool.ordered()[:limit]]
