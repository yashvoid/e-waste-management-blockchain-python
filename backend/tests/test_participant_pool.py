from datetime import UTC, datetime
from pathlib import Path

from app.blockchain.mining import open_chain
from app.blockchain.participants import SUSPEND_TYPE, ParticipantLedger
from app.node.pending_pool import PendingTransactionPool
from app.storage.chain_storage import open_chain_storage
from chain_helpers import mine, mine_and_add
from test_participants import _block_time, _register, _tx, _wallet, network  # noqa: F401


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_pool_rejects_business_transaction_from_suspended_wallet(tmp_path: Path, network) -> None:
    _, config = network
    with open_chain_storage(tmp_path / "data", config) as storage:
        pool = PendingTransactionPool(storage)
        storage.add_block(mine(config, storage.store.tip, [_register(network, "alice")], _block_time(1)))
        storage.add_block(mine(config, storage.store.tip, [_tx(config, "alice", SUSPEND_TYPE, {}, nonce=1)], _block_time(2)))
        assert pool.admit(_tx(config, "alice", "waste.record", {"x": 1}, nonce=2)).state == "rejected"
        assert pool.admit(_tx(config, "bob", "waste.record", {"x": 1})).state == "accepted"


def test_pool_admits_registration_once_per_wallet_in_block_selection(tmp_path: Path, network) -> None:
    _, config = network
    first = _register(network, "alice", nonce="n1", issued_at=_now())
    second = _register(network, "alice", nonce="n2", issued_at=_now())
    with open_chain_storage(tmp_path / "data", config) as storage:
        pool = PendingTransactionPool(storage)
        assert pool.admit(first).state == "accepted"
        assert pool.admit(second).state == "accepted"
        selected = pool.eligible_for_block(_now())
        assert len(selected) == 1


def test_pool_rejects_registration_with_expired_attestation(tmp_path: Path, network) -> None:
    _, config = network
    stale = _register(network, "alice", issued_at="2025-12-30T00:00:00Z")
    with open_chain_storage(tmp_path / "data", config) as storage:
        assert PendingTransactionPool(storage).admit(stale).state == "rejected"


def test_reorganization_recomputes_registration_and_suspension(network) -> None:
    _, config = network
    store = open_chain(config)
    genesis = store.tip
    _, pub = _wallet("alice")
    registration = _register(network, "alice")
    suspension = _tx(config, "alice", SUSPEND_TYPE, {}, nonce=1)

    a1, _ = mine_and_add(store, config, genesis, [registration], _block_time(1))
    mine_and_add(store, config, a1, [suspension], _block_time(2))
    assert ParticipantLedger.from_blocks(store.canonical_chain, config).participant(pub).suspended

    b1, _ = mine_and_add(store, config, genesis, [], _block_time(1))
    b2, _ = mine_and_add(store, config, b1, [], _block_time(2))
    _, update = mine_and_add(store, config, b2, [], _block_time(3))
    assert update.canonical_changed
    assert ParticipantLedger.from_blocks(store.canonical_chain, config).participant(pub) is None

    b4, _ = mine_and_add(store, config, store.tip, [registration], _block_time(4))
    participant = ParticipantLedger.from_blocks(store.canonical_chain, config).participant(pub)
    assert participant is not None and not participant.suspended
