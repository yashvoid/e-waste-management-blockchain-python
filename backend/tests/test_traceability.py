import pytest

from app.blockchain.ledger import ChainLedger
from app.blockchain.participants import ParticipantRuleError
from app.blockchain.traceability import (
    batch_status,
    can_view_history,
    involved_wallets,
    lineage,
    material_status,
)
from business_helpers import (
    COL,
    GEN,
    MP,
    REC,
    TRA,
    accept_tx,
    apply_block,
    at,
    batch_tx,
    correction_tx,
    deliver_to_recycler,
    make_network,
    process_tx,
    reject_tx,
    register_tx,
    request_tx,
    transfer_material_to_processor,
    wallet_pub,
)

STRANGER = "stranger"


@pytest.fixture
def network(tmp_path):
    return make_network(tmp_path)


@pytest.fixture
def ledger(network):
    _, config = network
    ledger = ChainLedger()
    apply_block(
        ledger,
        config,
        [
            register_tx(network, GEN, "Generator"),
            register_tx(network, COL, "Collector"),
            register_tx(network, TRA, "Transporter"),
            register_tx(network, REC, "Recycler"),
            register_tx(network, MP, "Material Processor"),
            register_tx(network, STRANGER, "Collector"),
        ],
        at(minutes=1),
    )
    return ledger


def _apply(ledger, network, transaction, minute):
    _, config = network
    apply_block(ledger, config, [transaction], at(minutes=minute))
    return transaction.txid


def _process_all(ledger, network, batch_id, outputs, residual=0, *, nonce=0, minute=20):
    _, config = network
    grams = sum(quantity for _, quantity in outputs) + residual
    op = process_tx(config, REC, batch_id, grams, outputs, residual, nonce=nonce)
    return _apply(ledger, network, op, minute)


def test_batch_is_not_completed_while_quantity_is_held(ledger, network) -> None:
    batch_id = deliver_to_recycler(ledger, network, 100_000)
    status = batch_status(ledger, batch_id)
    assert status.remaining_grams == 100_000
    assert status.completed is False


def test_transfer_alone_does_not_complete_a_batch(ledger, network) -> None:
    _, config = network
    batch = deliver_to_recycler(ledger, network, 100_000)
    status = batch_status(ledger, batch)
    assert status.completed is False
    assert status.processed_grams == 0


def test_partial_processing_is_not_batch_completion(ledger, network) -> None:
    _, config = network
    batch_id = deliver_to_recycler(ledger, network, 100_000)
    _process_all(ledger, network, batch_id, [("Copper", 60_000)], 0)
    status = batch_status(ledger, batch_id)
    assert status.remaining_grams == 40_000
    assert status.processed_grams == 60_000
    assert status.completed is False


def test_batch_completes_when_fully_processed_even_with_materials_remaining(ledger, network) -> None:
    batch_id = deliver_to_recycler(ledger, network, 100_000)
    _process_all(ledger, network, batch_id, [("Copper", 70_000)], 30_000)
    status = batch_status(ledger, batch_id)
    assert status.completed is True
    assert status.processed_grams == 100_000
    assert material_status(ledger, f"{ledger.processing.operations()[0].operation_id}-0").completed is False


def test_batch_conservation_holds_across_processing_and_discrepancy(ledger, network) -> None:
    batch_id = deliver_to_recycler(ledger, network, 100_000)
    _process_all(ledger, network, batch_id, [("Copper", 25_000)], 25_000)
    status = batch_status(ledger, batch_id)
    assert (
        status.remaining_grams + status.processed_grams + status.discrepancy_grams == status.quantity_grams
    )


def test_material_is_not_completed_while_quantity_remains(ledger, network) -> None:
    batch_id = deliver_to_recycler(ledger, network, 100_000)
    op = _process_all(ledger, network, batch_id, [("Copper", 100_000)], 0)
    status = material_status(ledger, f"{op}-0")
    assert status.remaining_grams == 100_000
    assert status.completed is False


def test_processor_fully_consuming_material_completes_it(ledger, network) -> None:
    _, config = network
    batch_id = deliver_to_recycler(ledger, network, 100_000)
    op = _process_all(ledger, network, batch_id, [("Copper", 100_000)], 0)
    material_id = f"{op}-0"
    transfer_material_to_processor(ledger, network, material_id, 100_000, minute=21)
    _apply(ledger, network, process_tx(config, MP, material_id, 100_000, [("Ingot", 90_000)], 10_000), 23)
    status = material_status(ledger, material_id)
    assert status.remaining_grams == 0
    assert status.completed is True
    assert status.processed_grams == 100_000


def test_material_lineage_links_material_to_operation_and_batch(ledger, network) -> None:
    batch_id = deliver_to_recycler(ledger, network, 100_000)
    op = _process_all(ledger, network, batch_id, [("Copper", 100_000)], 0)
    material = ledger.processing.material(f"{op}-0")
    assert material.source_operation == op
    assert material.parent_item == batch_id
    assert material.creator == wallet_pub(REC)
    kinds = [entry.kind for entry in lineage(ledger, material.material_id)]
    assert kinds == ["batch", "transfer", "transfer", "transfer", "processing"]


def test_lineage_runs_from_origin_to_material_in_order(ledger, network) -> None:
    batch_id = deliver_to_recycler(ledger, network, 100_000)
    op = _process_all(ledger, network, batch_id, [("Copper", 100_000)], 0)
    entries = lineage(ledger, f"{op}-0")
    assert entries[0].record_id == batch_id
    assert entries[0].participants == (wallet_pub(GEN),)
    assert entries[-1].record_id == op
    assert entries[-1].participants == (wallet_pub(REC),)


def test_multi_generation_lineage_traces_back_through_each_operation(ledger, network) -> None:
    _, config = network
    batch_id = deliver_to_recycler(ledger, network, 100_000)
    op1 = _process_all(ledger, network, batch_id, [("Mixed", 100_000)], 0)
    transfer_material_to_processor(ledger, network, f"{op1}-0", 100_000, minute=21)
    op2 = _apply(ledger, network, process_tx(config, MP, f"{op1}-0", 100_000, [("Ingot", 100_000)], 0), 23)
    entries = lineage(ledger, f"{op2}-0")
    assert [entry.record_id for entry in entries if entry.kind == "processing"] == [op1, op2]
    assert entries[0].record_id == batch_id
    assert ledger.processing.material(f"{op2}-0").parent_item == f"{op1}-0"


def test_correction_by_batch_generator_is_recorded_without_changing_quantities(ledger, network) -> None:
    _, config = network
    batch_id = deliver_to_recycler(ledger, network, 100_000)
    before = ledger.business.total_held(batch_id)
    correction = _apply(ledger, network, correction_tx(config, GEN, batch_id, "Weight was recounted"), 20)
    assert ledger.business.total_held(batch_id) == before
    assert ledger.business.batch(batch_id).quantity_grams == 100_000
    assert ledger.processing.corrections_for(batch_id)[0].correction_id == correction
    assert any(entry.kind == "correction" for entry in lineage(ledger, batch_id))


def test_correction_by_processor_references_operation(ledger, network) -> None:
    _, config = network
    batch_id = deliver_to_recycler(ledger, network, 100_000)
    op = _process_all(ledger, network, batch_id, [("Copper", 100_000)], 0)
    _apply(ledger, network, correction_tx(config, REC, op, "Output label was wrong"), 21)
    assert ledger.processing.corrections_for(op)[0].author == wallet_pub(REC)
    assert ledger.processing.operation(op).residual_grams == 0


def test_correction_by_another_wallet_is_rejected(ledger, network) -> None:
    _, config = network
    batch_id = deliver_to_recycler(ledger, network, 100_000)
    correction = correction_tx(config, STRANGER, batch_id, "Not mine to correct")
    with pytest.raises(ParticipantRuleError, match="Only the wallet that created"):
        ledger.check(correction, block_timestamp=at(minutes=20), height=1, config=config)


def test_correction_of_missing_record_is_rejected(ledger, network) -> None:
    _, config = network
    correction = correction_tx(config, GEN, "ff" * 32, "Nothing here")
    with pytest.raises(ParticipantRuleError, match="existing batch or processing record"):
        ledger.check(correction, block_timestamp=at(minutes=20), height=1, config=config)


def test_correction_of_a_material_is_rejected(ledger, network) -> None:
    _, config = network
    batch_id = deliver_to_recycler(ledger, network, 100_000)
    op = _process_all(ledger, network, batch_id, [("Copper", 100_000)], 0)
    correction = correction_tx(config, REC, f"{op}-0", "Label fix")
    with pytest.raises(ParticipantRuleError, match="existing batch or processing record"):
        ledger.check(correction, block_timestamp=at(minutes=21), height=1, config=config)


@pytest.mark.parametrize("explanation", ["", "   "])
def test_correction_requires_an_explanation(ledger, network, explanation) -> None:
    _, config = network
    batch_id = deliver_to_recycler(ledger, network, 100_000)
    correction = correction_tx(config, GEN, batch_id, explanation)
    with pytest.raises(ParticipantRuleError, match="correction explanation"):
        ledger.check(correction, block_timestamp=at(minutes=20), height=1, config=config)


def test_generator_keeps_history_access_after_transferring_everything(ledger, network) -> None:
    batch_id = deliver_to_recycler(ledger, network, 100_000)
    assert ledger.business.holding(wallet_pub(GEN), batch_id) == 0
    assert can_view_history(ledger, wallet_pub(GEN), batch_id)


def test_recycler_and_earlier_custodians_can_view_material_history(ledger, network) -> None:
    batch_id = deliver_to_recycler(ledger, network, 100_000)
    op = _process_all(ledger, network, batch_id, [("Copper", 100_000)], 0)
    material_id = f"{op}-0"
    for label in (GEN, COL, TRA, REC):
        assert can_view_history(ledger, wallet_pub(label), material_id)


def test_uninvolved_wallets_cannot_view_history(ledger, network) -> None:
    batch_id = deliver_to_recycler(ledger, network, 100_000)
    op = _process_all(ledger, network, batch_id, [("Copper", 100_000)], 0)
    assert not can_view_history(ledger, wallet_pub(STRANGER), batch_id)
    assert not can_view_history(ledger, wallet_pub(MP), f"{op}-0")


def test_pending_transfer_receiver_is_involved_in_history(ledger, network) -> None:
    _, config = network
    batch = batch_tx(config, GEN, 1_000, description="Second lot")
    _apply(ledger, network, batch, 2)
    request = request_tx(config, GEN, batch.txid, COL, 1_000, nonce=9)
    _apply(ledger, network, request, 30)
    assert wallet_pub(COL) in involved_wallets(ledger, batch.txid)
    assert not can_view_history(ledger, wallet_pub(STRANGER), batch.txid)


def test_unknown_item_has_no_involved_wallets(ledger) -> None:
    assert involved_wallets(ledger, "ff" * 32) == frozenset()


def test_residual_is_reported_without_counting_it_as_remaining(ledger, network) -> None:
    batch_id = deliver_to_recycler(ledger, network, 100_000)
    _process_all(ledger, network, batch_id, [("Copper", 20_000)], 30_000)
    status = batch_status(ledger, batch_id)
    assert status.residual_grams == 30_000
    assert status.processed_grams == 50_000
    assert status.remaining_grams == 50_000
    assert status.remaining_grams + status.processed_grams + status.discrepancy_grams == status.quantity_grams


def test_material_residual_is_reported_once_on_the_material_processed(ledger, network) -> None:
    _, config = network
    batch_id = deliver_to_recycler(ledger, network, 100_000)
    op = _process_all(ledger, network, batch_id, [("Copper", 100_000)], 0)
    material_id = f"{op}-0"
    transfer_material_to_processor(ledger, network, material_id, 100_000, minute=21)
    _apply(ledger, network, process_tx(config, MP, material_id, 100_000, [("Ingot", 90_000)], 10_000), 23)
    assert material_status(ledger, material_id).residual_grams == 10_000
    assert batch_status(ledger, batch_id).residual_grams == 0


def test_material_accounting_balances_with_receipt_discrepancy_and_residual(ledger, network) -> None:
    _, config = network
    batch_id = deliver_to_recycler(ledger, network, 100_000)
    op = _process_all(ledger, network, batch_id, [("Copper", 100_000)], 0)
    material_id = f"{op}-0"
    request = request_tx(config, REC, material_id, MP, 100_000)
    _apply(ledger, network, request, 30)
    _apply(ledger, network, accept_tx(config, MP, request.txid, 95_000, reason="Damaged in transit"), 31)
    _apply(ledger, network, process_tx(config, MP, material_id, 95_000, [("Ingot", 80_000)], 15_000), 33)
    status = material_status(ledger, material_id)
    assert (status.remaining_grams, status.processed_grams, status.residual_grams, status.discrepancy_grams) == (
        0,
        95_000,
        15_000,
        5_000,
    )
    assert status.remaining_grams + status.processed_grams + status.discrepancy_grams == status.quantity_grams
    assert status.completed is True


def test_rejected_transfer_receiver_is_involved_in_history(ledger, network) -> None:
    _, config = network
    batch = batch_tx(config, GEN, 1_000, description="Declined lot")
    _apply(ledger, network, batch, 2)
    request = request_tx(config, GEN, batch.txid, COL, 1_000, nonce=9)
    _apply(ledger, network, request, 30)
    _apply(ledger, network, reject_tx(config, COL, request.txid, "Not collecting this lot"), 31)
    assert ledger.business.holding(wallet_pub(GEN), batch.txid) == 1_000
    assert can_view_history(ledger, wallet_pub(COL), batch.txid)
    assert not can_view_history(ledger, wallet_pub(STRANGER), batch.txid)
