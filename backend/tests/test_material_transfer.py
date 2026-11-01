import pytest

from app.blockchain.ledger import ChainLedger
from app.blockchain.participants import ParticipantRuleError
from app.blockchain.traceability import can_view_history, lineage, material_status
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
    cancel_tx,
    deliver_to_recycler,
    make_network,
    process_tx,
    register_tx,
    reject_tx,
    request_tx,
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


def _recycler_material(ledger, network, grams=100_000):
    _, config = network
    batch_id = deliver_to_recycler(ledger, network, grams)
    op = _apply(ledger, network, process_tx(config, REC, batch_id, grams, [("Copper", grams)], 0), 20)
    return batch_id, f"{op}-0"


def test_recycler_transfers_full_material_to_processor(ledger, network) -> None:
    _, config = network
    _, material = _recycler_material(ledger, network)
    request = request_tx(config, REC, material, MP, 100_000)
    _apply(ledger, network, request, 30)
    _apply(ledger, network, accept_tx(config, MP, request.txid, 100_000), 31)
    assert ledger.business.holding(wallet_pub(REC), material) == 0
    assert ledger.business.holding(wallet_pub(MP), material) == 100_000


def test_partial_material_receipt_records_discrepancy(ledger, network) -> None:
    _, config = network
    _, material = _recycler_material(ledger, network)
    request = request_tx(config, REC, material, MP, 100_000)
    _apply(ledger, network, request, 30)
    _apply(ledger, network, accept_tx(config, MP, request.txid, 60_000, reason="Damaged in transit"), 31)
    assert ledger.business.holding(wallet_pub(MP), material) == 60_000
    assert ledger.business.discrepancy(material) == 40_000
    total = (
        ledger.business.total_held(material) + ledger.business.discrepancy(material)
    )
    assert total == 100_000


def test_recycler_cannot_transfer_batch_to_processor(ledger, network) -> None:
    _, config = network
    batch_id = deliver_to_recycler(ledger, network, 100_000)
    request = request_tx(config, REC, batch_id, MP, 1_000)
    with pytest.raises(ParticipantRuleError, match="A Recycler can only transfer recovered material"):
        ledger.check(request, block_timestamp=at(minutes=30), height=1, config=config)


def test_recycler_cannot_send_material_to_collector(ledger, network) -> None:
    _, config = network
    _, material = _recycler_material(ledger, network)
    request = request_tx(config, REC, material, COL, 1_000)
    with pytest.raises(ParticipantRuleError, match="A Recycler can only transfer to a Material Processor"):
        ledger.check(request, block_timestamp=at(minutes=30), height=1, config=config)


def test_generator_cannot_transfer_material(ledger, network) -> None:
    _, config = network
    _, material = _recycler_material(ledger, network)
    request = request_tx(config, GEN, material, COL, 1_000)
    with pytest.raises(ParticipantRuleError, match="Recovered material can only be transferred"):
        ledger.check(request, block_timestamp=at(minutes=30), height=1, config=config)


def test_material_processor_cannot_transfer_outputs_onward(ledger, network) -> None:
    _, config = network
    _, material = _recycler_material(ledger, network)
    request = request_tx(config, REC, material, MP, 100_000)
    _apply(ledger, network, request, 30)
    _apply(ledger, network, accept_tx(config, MP, request.txid, 100_000), 31)
    onward = request_tx(config, MP, material, REC, 1_000)
    with pytest.raises(ParticipantRuleError, match="Recovered material can only be transferred"):
        ledger.check(onward, block_timestamp=at(minutes=32), height=1, config=config)


def test_material_transfer_cannot_exceed_available_quantity(ledger, network) -> None:
    _, config = network
    _, material = _recycler_material(ledger, network)
    request = request_tx(config, REC, material, MP, 100_001)
    with pytest.raises(ParticipantRuleError, match="available unreserved quantity"):
        ledger.check(request, block_timestamp=at(minutes=30), height=1, config=config)


def test_pending_material_transfer_reserves_quantity(ledger, network) -> None:
    _, config = network
    _, material = _recycler_material(ledger, network)
    _apply(ledger, network, request_tx(config, REC, material, MP, 60_000), 30)
    second = request_tx(config, REC, material, MP, 60_000, nonce=1)
    with pytest.raises(ParticipantRuleError, match="available unreserved quantity"):
        ledger.check(second, block_timestamp=at(minutes=31), height=1, config=config)


def test_only_designated_processor_can_accept_material(ledger, network) -> None:
    _, config = network
    _, material = _recycler_material(ledger, network)
    request = request_tx(config, REC, material, MP, 100_000)
    _apply(ledger, network, request, 30)
    misdirected = accept_tx(config, REC, request.txid, 100_000)
    with pytest.raises(ParticipantRuleError, match="designated receiver"):
        ledger.check(misdirected, block_timestamp=at(minutes=31), height=1, config=config)


def test_rejected_material_transfer_keeps_ownership_with_recycler(ledger, network) -> None:
    _, config = network
    _, material = _recycler_material(ledger, network)
    request = request_tx(config, REC, material, MP, 100_000)
    _apply(ledger, network, request, 30)
    _apply(ledger, network, reject_tx(config, MP, request.txid, "Wrong material"), 31)
    assert ledger.business.holding(wallet_pub(REC), material) == 100_000
    assert ledger.business.holding(wallet_pub(MP), material) == 0


def test_cancelled_material_transfer_releases_reservation(ledger, network) -> None:
    _, config = network
    _, material = _recycler_material(ledger, network)
    request = request_tx(config, REC, material, MP, 100_000)
    _apply(ledger, network, request, 30)
    _apply(ledger, network, cancel_tx(config, REC, request.txid), 31)
    assert ledger.business.available(wallet_pub(REC), material) == 100_000


def test_expired_material_transfer_keeps_ownership(ledger, network) -> None:
    _, config = network
    _, material = _recycler_material(ledger, network)
    request = request_tx(config, REC, material, MP, 100_000)
    _apply(ledger, network, request, 30)
    ledger.begin_block(at(hours=49))
    assert ledger.business.transfer(request.txid).status == "expired"
    assert ledger.business.holding(wallet_pub(REC), material) == 100_000
    late = accept_tx(config, MP, request.txid, 100_000)
    with pytest.raises(ParticipantRuleError, match="no longer pending"):
        ledger.check(late, block_timestamp=at(hours=49), height=1, config=config)


def test_material_with_pending_transfer_is_not_completed(ledger, network) -> None:
    _, config = network
    _, material = _recycler_material(ledger, network)
    _apply(ledger, network, request_tx(config, REC, material, MP, 100_000), 30)
    status = material_status(ledger, material)
    assert status.pending_grams == 100_000
    assert status.completed is False


def test_processor_fully_consuming_received_material_completes_it(ledger, network) -> None:
    _, config = network
    _, material = _recycler_material(ledger, network)
    request = request_tx(config, REC, material, MP, 100_000)
    _apply(ledger, network, request, 30)
    _apply(ledger, network, accept_tx(config, MP, request.txid, 100_000), 31)
    _apply(ledger, network, process_tx(config, MP, material, 100_000, [("Ingot", 100_000)], 0), 32)
    status = material_status(ledger, material)
    assert status.remaining_grams == 0
    assert status.completed is True


def test_processor_cannot_process_more_than_received(ledger, network) -> None:
    _, config = network
    _, material = _recycler_material(ledger, network)
    request = request_tx(config, REC, material, MP, 100_000)
    _apply(ledger, network, request, 30)
    _apply(ledger, network, accept_tx(config, MP, request.txid, 60_000, reason="Short load"), 31)
    overspend = process_tx(config, MP, material, 60_001, [("Ingot", 60_001)], 0)
    with pytest.raises(ParticipantRuleError, match="available unreserved inventory"):
        ledger.check(overspend, block_timestamp=at(minutes=32), height=1, config=config)


def test_lineage_includes_material_custody_transfer(ledger, network) -> None:
    _, config = network
    _, material = _recycler_material(ledger, network)
    request = request_tx(config, REC, material, MP, 100_000)
    _apply(ledger, network, request, 30)
    _apply(ledger, network, accept_tx(config, MP, request.txid, 100_000), 31)
    kinds = [entry.kind for entry in lineage(ledger, material)]
    assert kinds == ["batch", "transfer", "transfer", "transfer", "processing", "transfer"]


def test_processor_gains_history_access_after_receipt(ledger, network) -> None:
    _, config = network
    _, material = _recycler_material(ledger, network)
    assert not can_view_history(ledger, wallet_pub(MP), material)
    request = request_tx(config, REC, material, MP, 100_000)
    _apply(ledger, network, request, 30)
    assert can_view_history(ledger, wallet_pub(MP), material)
    _apply(ledger, network, accept_tx(config, MP, request.txid, 100_000), 31)
    assert can_view_history(ledger, wallet_pub(REC), material)
    assert not can_view_history(ledger, wallet_pub(STRANGER), material)
