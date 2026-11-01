from dataclasses import replace

import pytest

from app.blockchain.ledger import ChainLedger
from app.blockchain.processing import material_id_for
from app.blockchain.traceability import batch_status, lineage, material_status
from app.blockchain.validation import ValidationError, validate_block
from app.node.pending_pool import PendingTransactionPool
from app.storage.chain_storage import open_chain_storage
from business_helpers import (
    COL,
    GEN,
    MP,
    REC,
    TRA,
    accept_tx,
    at,
    batch_tx,
    correction_tx,
    make_network,
    process_tx,
    register_tx,
    request_tx,
    wallet_pub,
)
from chain_helpers import mine


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
            register_tx(network, MP, "Material Processor"),
        ]
        chain.add_block(mine(config, chain.store.tip, registrations, at(minutes=1)))
        yield chain


def _confirm(storage, config, transactions, when):
    block = mine(config, storage.store.tip, transactions, when)
    storage.add_block(block)
    return block


def _confirmed_recycler_batch(storage, network, grams=100_000):
    _, config = network
    batch = batch_tx(config, GEN, grams)
    _confirm(storage, config, [batch], at(minutes=2))
    hops = ((GEN, COL), (COL, TRA), (TRA, REC))
    for step, (sender, receiver) in enumerate(hops):
        request = request_tx(config, sender, batch.txid, receiver, grams, nonce=step)
        _confirm(storage, config, [request], at(minutes=3 + step * 2))
        _confirm(storage, config, [accept_tx(config, receiver, request.txid, grams)], at(minutes=4 + step * 2))
    return batch.txid


def test_pool_admits_processing_and_block_confirms_it(storage, network) -> None:
    _, config = network
    batch_id = _confirmed_recycler_batch(storage, network)
    pool = PendingTransactionPool(storage)
    op = process_tx(config, REC, batch_id, 100_000, [("Copper", 100_000)], 0)
    assert pool.admit(op).state == "accepted"
    assert pool.admit(op).state == "known"
    _confirm(storage, config, [op], at(minutes=10))
    assert pool.admit(op).state == "confirmed"
    ledger = ChainLedger.from_blocks(storage.store.canonical_chain, config)
    assert ledger.business.holding(wallet_pub(REC), batch_id) == 0
    assert ledger.processing.material(material_id_for(op.txid, 0)).quantity_grams == 100_000


def test_pool_rejects_forged_processing_signature(storage, network) -> None:
    _, config = network
    batch_id = _confirmed_recycler_batch(storage, network)
    pool = PendingTransactionPool(storage)
    op = process_tx(config, REC, batch_id, 100_000, [("Copper", 100_000)], 0)
    other = process_tx(config, REC, batch_id, 100_000, [("Copper", 100_000)], 0, nonce=9)
    assert pool.admit(replace(op, signature=other.signature)).state == "rejected"


def test_overlapping_processing_is_admitted_but_block_selection_skips_one(storage, network) -> None:
    _, config = network
    batch_id = _confirmed_recycler_batch(storage, network)
    pool = PendingTransactionPool(storage)
    first = process_tx(config, REC, batch_id, 60_000, [("Copper", 60_000)], 0, nonce=1)
    second = process_tx(config, REC, batch_id, 60_000, [("Copper", 60_000)], 0, nonce=2)
    assert pool.admit(first).state == "accepted"
    assert pool.admit(second).state == "accepted"
    selected = pool.eligible_for_block(at(minutes=10))
    assert len(selected) == 1
    assert selected[0].txid in (first.txid, second.txid)


def test_processing_repeated_in_later_block_is_rejected(storage, network) -> None:
    _, config = network
    batch_id = _confirmed_recycler_batch(storage, network)
    op = process_tx(config, REC, batch_id, 100_000, [("Copper", 100_000)], 0)
    _confirm(storage, config, [op], at(minutes=10))
    parent = storage.store.tip
    repeat = mine(config, parent, [op], at(minutes=11))
    with pytest.raises(ValidationError):
        validate_block(repeat, config, storage.store.ancestry(parent))


def test_reorganization_removes_processing_and_restores_inventory(storage, network) -> None:
    _, config = network
    batch_id = _confirmed_recycler_batch(storage, network)
    op = process_tx(config, REC, batch_id, 100_000, [("Copper", 100_000)], 0)
    op_block = _confirm(storage, config, [op], at(minutes=10))
    before = ChainLedger.from_blocks(storage.store.canonical_chain, config)
    assert before.processing.operation(op.txid) is not None

    branch_tip = storage.store.blocks_by_hash[op_block.previous_hash]
    updates = []
    for minute in (11, 12, 13):
        branch_tip = mine(config, branch_tip, [], at(minutes=minute, seconds=1))
        updates.append(storage.add_block(branch_tip))

    removed = [transaction for update in updates for transaction in update.removed_transactions]
    assert storage.store.tip.block_hash == branch_tip.block_hash
    assert op.txid in {transaction.txid for transaction in removed}
    rebuilt = ChainLedger.from_blocks(storage.store.canonical_chain, config)
    assert rebuilt.processing.operations() == ()
    assert rebuilt.processing.materials() == ()
    assert rebuilt.business.holding(wallet_pub(REC), batch_id) == 100_000


def test_reorganization_readmits_processing_to_pool_when_still_valid(storage, network) -> None:
    _, config = network
    batch_id = _confirmed_recycler_batch(storage, network)
    op = process_tx(config, REC, batch_id, 100_000, [("Copper", 100_000)], 0)
    op_block = _confirm(storage, config, [op], at(minutes=10))

    branch_tip = storage.store.blocks_by_hash[op_block.previous_hash]
    updates = []
    for minute in (11, 12, 13):
        branch_tip = mine(config, branch_tip, [], at(minutes=minute, seconds=1))
        updates.append(storage.add_block(branch_tip))
    removed = [transaction for update in updates for transaction in update.removed_transactions]

    pool = PendingTransactionPool(storage)
    pool.reconcile(removed)
    assert pool.get(op.txid) is not None


def test_rebuilt_processing_state_is_identical_for_the_same_chain(storage, network) -> None:
    _, config = network
    batch_id = _confirmed_recycler_batch(storage, network)
    _confirm(storage, config, [process_tx(config, REC, batch_id, 100_000, [("Copper", 100_000)], 0)], at(minutes=10))
    first = ChainLedger.from_blocks(storage.store.canonical_chain, config)
    second = ChainLedger.from_blocks(list(storage.store.canonical_chain), config)
    assert first.processing.operations() == second.processing.operations()
    assert first.processing.materials() == second.processing.materials()


def _ledger(storage, config) -> ChainLedger:
    return ChainLedger.from_blocks(storage.store.canonical_chain, config)


def _fork_from(storage, config, parent, minutes):
    removed = []
    tip = parent
    for minute in minutes:
        tip = mine(config, tip, [], at(minutes=minute, seconds=1))
        removed.extend(storage.add_block(tip).removed_transactions)
    return removed


def test_reorganization_removes_material_transfer_and_restores_it(storage, network) -> None:
    _, config = network
    batch_id = _confirmed_recycler_batch(storage, network)
    op = process_tx(config, REC, batch_id, 100_000, [("Copper", 100_000)], 0)
    op_block = _confirm(storage, config, [op], at(minutes=10))
    material_id = material_id_for(op.txid, 0)
    request = request_tx(config, REC, material_id, MP, 100_000)
    accept = accept_tx(config, MP, request.txid, 100_000)
    _confirm(storage, config, [request], at(minutes=11))
    _confirm(storage, config, [accept], at(minutes=12))
    before = _ledger(storage, config)
    before_lineage = [(entry.kind, entry.record_id) for entry in lineage(before, material_id)]
    assert before.business.holding(wallet_pub(MP), material_id) == 100_000

    removed = _fork_from(storage, config, op_block, (13, 14, 15))
    assert {request.txid, accept.txid} <= {transaction.txid for transaction in removed}
    after = _ledger(storage, config)
    assert after.business.holding(wallet_pub(REC), material_id) == 100_000
    assert after.business.holding(wallet_pub(MP), material_id) == 0
    assert after.business.transfer(request.txid) is None
    assert len(lineage(after, material_id)) == len(before_lineage) - 1

    pool = PendingTransactionPool(storage)
    pool.reconcile(removed)
    assert pool.get(request.txid) is not None

    _confirm(storage, config, [request], at(minutes=20))
    _confirm(storage, config, [accept], at(minutes=21))
    restored = _ledger(storage, config)
    assert [(entry.kind, entry.record_id) for entry in lineage(restored, material_id)] == before_lineage
    assert restored.business.holding(wallet_pub(MP), material_id) == 100_000


def test_reorganization_reopens_material_completion(storage, network) -> None:
    _, config = network
    batch_id = _confirmed_recycler_batch(storage, network)
    op = process_tx(config, REC, batch_id, 100_000, [("Copper", 100_000)], 0)
    _confirm(storage, config, [op], at(minutes=10))
    material_id = material_id_for(op.txid, 0)
    request = request_tx(config, REC, material_id, MP, 100_000)
    _confirm(storage, config, [request], at(minutes=11))
    accept_block = _confirm(storage, config, [accept_tx(config, MP, request.txid, 100_000)], at(minutes=12))
    processing = process_tx(config, MP, material_id, 100_000, [("Ingot", 100_000)], 0)
    _confirm(storage, config, [processing], at(minutes=13))
    assert material_status(_ledger(storage, config), material_id).completed is True

    _fork_from(storage, config, accept_block, (14, 15, 16))
    after = _ledger(storage, config)
    status = material_status(after, material_id)
    assert status.completed is False
    assert status.remaining_grams == 100_000
    assert batch_status(after, batch_id).completed is True


def test_reorganization_restores_residual_and_batch_completion(storage, network) -> None:
    _, config = network
    batch_id = _confirmed_recycler_batch(storage, network)
    op = process_tx(config, REC, batch_id, 100_000, [("Copper", 70_000)], 30_000)
    op_block = _confirm(storage, config, [op], at(minutes=10))
    before = batch_status(_ledger(storage, config), batch_id)
    assert before.completed is True
    assert before.residual_grams == 30_000

    _fork_from(storage, config, storage.store.blocks_by_hash[op_block.previous_hash], (11, 12, 13))
    after = batch_status(_ledger(storage, config), batch_id)
    assert after.completed is False
    assert after.residual_grams == 0
    assert after.remaining_grams == 100_000

    _confirm(storage, config, [op], at(minutes=20))
    restored = batch_status(_ledger(storage, config), batch_id)
    assert restored.completed is True
    assert restored.residual_grams == 30_000


def test_reorganization_removes_and_readmits_corrections(storage, network) -> None:
    _, config = network
    batch_id = _confirmed_recycler_batch(storage, network)
    parent = storage.store.tip
    correction = correction_tx(config, GEN, batch_id, "Weight was recounted")
    _confirm(storage, config, [correction], at(minutes=10))
    assert _ledger(storage, config).processing.corrections_for(batch_id)[0].correction_id == correction.txid

    removed = _fork_from(storage, config, parent, (11, 12, 13))
    assert correction.txid in {transaction.txid for transaction in removed}
    after = _ledger(storage, config)
    assert after.processing.corrections_for(batch_id) == ()
    assert all(entry.kind != "correction" for entry in lineage(after, batch_id))
    assert after.business.batch(batch_id).quantity_grams == 100_000

    pool = PendingTransactionPool(storage)
    pool.reconcile(removed)
    assert pool.get(correction.txid) is not None
