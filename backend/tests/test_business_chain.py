from dataclasses import replace

import pytest

from app.blockchain.ledger import ChainLedger
from app.blockchain.mining import open_chain
from app.blockchain.validation import ValidationError, validate_block
from app.node.pending_pool import PendingTransactionPool
from app.storage.chain_storage import open_chain_storage
from business_helpers import (
    COL,
    GEN,
    REC,
    TRA,
    at,
    batch_tx,
    make_network,
    register_tx,
    request_tx,
    wallet_pub,
)
from chain_helpers import mine, mine_and_add


@pytest.fixture
def network(tmp_path):
    return make_network(tmp_path)


@pytest.fixture
def storage(tmp_path, network):
    _, config = network
    with open_chain_storage(tmp_path / "chain", config) as chain:
        registrations = [
            register_tx(network, GEN, "Generator"),
            register_tx(network, COL, "Collector"),
            register_tx(network, TRA, "Transporter"),
            register_tx(network, REC, "Recycler"),
        ]
        chain.add_block(mine(config, chain.store.tip, registrations, at(minutes=1)))
        yield chain


def _confirm(storage, config, transactions, when):
    block = mine(config, storage.store.tip, transactions, when)
    storage.add_block(block)
    return block


def _confirmed_batch(storage, network, grams=100_000):
    _, config = network
    batch = batch_tx(config, GEN, grams)
    _confirm(storage, config, [batch], at(minutes=2))
    return batch


def test_pool_admits_batch_and_block_confirms_it(storage, network) -> None:
    _, config = network
    pool = PendingTransactionPool(storage)
    batch = batch_tx(config, GEN, 100_000)
    assert pool.admit(batch).state == "accepted"
    assert pool.admit(batch).state == "known"
    _confirm(storage, config, [batch], at(minutes=2))
    assert pool.admit(batch).state == "confirmed"


def test_invalid_signature_is_rejected_by_pool(storage, network) -> None:
    _, config = network
    pool = PendingTransactionPool(storage)
    batch = batch_tx(config, GEN, 100_000)
    other = batch_tx(config, GEN, 100_000, nonce=9)
    forged = replace(batch, signature=other.signature)
    assert pool.admit(forged).state == "rejected"


def test_pending_transfer_reserves_nothing_until_confirmed(storage, network) -> None:
    _, config = network
    batch = _confirmed_batch(storage, network)
    pool = PendingTransactionPool(storage)
    transfer = request_tx(config, GEN, batch.txid, COL, 40_000)
    assert pool.admit(transfer).state == "accepted"
    ledger = ChainLedger.from_blocks(storage.store.canonical_chain, config)
    assert ledger.business.reserved(wallet_pub(GEN), batch.txid) == 0
    _confirm(storage, config, [transfer], at(minutes=3))
    ledger = ChainLedger.from_blocks(storage.store.canonical_chain, config)
    assert ledger.business.reserved(wallet_pub(GEN), batch.txid) == 40_000


def test_pool_admits_transfers_that_together_overspend_but_block_selection_skips_one(storage, network) -> None:
    _, config = network
    batch = _confirmed_batch(storage, network, 100_000)
    pool = PendingTransactionPool(storage)
    first = request_tx(config, GEN, batch.txid, COL, 60_000, nonce=1)
    second = request_tx(config, GEN, batch.txid, COL, 60_000, nonce=2)
    assert pool.admit(first).state == "accepted"
    assert pool.admit(second).state == "accepted"
    selected = pool.eligible_for_block(at(minutes=4))
    assert len(selected) == 1
    assert selected[0].txid in (first.txid, second.txid)


def test_batch_repeated_in_later_block_is_rejected(storage, network) -> None:
    _, config = network
    batch = _confirmed_batch(storage, network)
    parent = storage.store.tip
    repeat = mine(config, parent, [batch], at(minutes=3))
    with pytest.raises(ValidationError, match="repeats"):
        validate_block(repeat, config, storage.store.ancestry(parent))


def test_reorganization_removes_batch_and_transfer_and_pool_reconciles(storage, network) -> None:
    _, config = network
    batch = batch_tx(config, GEN, 100_000)
    transfer = request_tx(config, GEN, batch.txid, COL, 40_000)
    confirmed_batch = mine(config, storage.store.tip, [batch], at(minutes=2))
    storage.add_block(confirmed_batch)
    storage.add_block(mine(config, confirmed_batch, [transfer], at(minutes=3)))
    fork_point = storage.store.blocks_by_hash[confirmed_batch.previous_hash]
    before = ChainLedger.from_blocks(storage.store.canonical_chain, config)
    assert before.business.reserved(wallet_pub(GEN), batch.txid) == 40_000

    branch_tip = fork_point
    updates = []
    for minute in (2, 3, 4):
        branch_tip = mine(config, branch_tip, [], at(minutes=minute, seconds=1))
        updates.append(storage.add_block(branch_tip))

    removed = [transaction for update in updates for transaction in update.removed_transactions]
    assert any(update.canonical_changed for update in updates)
    assert storage.store.tip.block_hash == branch_tip.block_hash
    rebuilt = ChainLedger.from_blocks(storage.store.canonical_chain, config)
    assert rebuilt.business.batches() == ()
    assert rebuilt.business.transfers() == ()
    assert {transaction.txid for transaction in removed} == {batch.txid, transfer.txid}

    pool = PendingTransactionPool(storage)
    pool.reconcile(removed)
    assert pool.get(batch.txid) is not None
    assert pool.get(transfer.txid) is None


def test_expiry_is_deterministic_across_rebuilds(network) -> None:
    _, config = network
    store = open_chain(config)
    registrations = mine_and_add(
        store,
        config,
        store.tip,
        [register_tx(network, GEN, "Generator"), register_tx(network, COL, "Collector")],
        at(minutes=1),
    )[0]
    batch = batch_tx(config, GEN, 100_000)
    batch_block = mine_and_add(store, config, registrations, [batch], at(minutes=2))[0]
    transfer = request_tx(config, GEN, batch.txid, COL, 100_000)
    parent = mine_and_add(store, config, batch_block, [transfer], at(minutes=3))[0]

    statuses = {}
    for hours in range(1, 49):
        parent = mine_and_add(store, config, parent, [], at(minutes=3, hours=hours))[0]
        ledger = ChainLedger.from_blocks(store.canonical_chain, config)
        statuses[hours] = ledger.business.transfer(transfer.txid).status

    assert statuses[47] == "pending"
    assert statuses[48] == "expired"
    first = ChainLedger.from_blocks(store.canonical_chain, config)
    second = ChainLedger.from_blocks(list(store.canonical_chain), config)
    assert first.business.transfers() == second.business.transfers()
    assert first.business.available(wallet_pub(GEN), batch.txid) == 100_000
