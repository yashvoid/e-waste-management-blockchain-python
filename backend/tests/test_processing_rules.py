import pytest

from app.blockchain.ledger import ChainLedger
from app.blockchain.participants import ParticipantRuleError
from business_helpers import (
    COL,
    GEN,
    MP,
    REC,
    TRA,
    apply_block,
    at,
    batch_tx,
    deliver_to_recycler,
    make_network,
    process_tx,
    register_tx,
    suspend_tx,
    wallet_pub,
)


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
        ],
        at(minutes=1),
    )
    return ledger


def _apply(ledger, network, transaction, minute):
    _, config = network
    apply_block(ledger, config, [transaction], at(minutes=minute))
    return transaction.txid


def _recycler_batch(ledger, network, grams=100_000, label="Old laptops"):
    return deliver_to_recycler(ledger, network, grams, label=label)


def test_recycler_processes_batch_into_recovered_materials(ledger, network) -> None:
    _, config = network
    batch_id = _recycler_batch(ledger, network)
    op = process_tx(config, REC, batch_id, 100_000, [("Copper", 60_000), ("Plastic", 30_000)], 10_000, method="shred")
    _apply(ledger, network, op, 20)

    assert ledger.business.holding(wallet_pub(REC), batch_id) == 0
    assert ledger.processing.operation(op.txid).processor == wallet_pub(REC)
    materials = ledger.processing.materials()
    assert [m.description for m in materials] == ["Copper", "Plastic"]
    assert [m.quantity_grams for m in materials] == [60_000, 30_000]
    assert all(ledger.business.holding(wallet_pub(REC), m.material_id) == m.quantity_grams for m in materials)


def test_unregistered_wallet_cannot_process(ledger, network) -> None:
    _, config = network
    batch_id = _recycler_batch(ledger, network)
    op = process_tx(config, "stranger", batch_id, 100_000, [("Copper", 100_000)], 0)
    with pytest.raises(ParticipantRuleError, match="registered Recycler or Material Processor"):
        ledger.check(op, block_timestamp=at(minutes=20), height=1, config=config)


def test_collector_cannot_process(ledger, network) -> None:
    _, config = network
    batch_id = _recycler_batch(ledger, network)
    op = process_tx(config, COL, batch_id, 1, [("Copper", 1)], 0)
    with pytest.raises(ParticipantRuleError, match="registered Recycler or Material Processor"):
        ledger.check(op, block_timestamp=at(minutes=20), height=1, config=config)


def test_suspended_recycler_cannot_process(ledger, network) -> None:
    _, config = network
    batch_id = _recycler_batch(ledger, network)
    _apply(ledger, network, suspend_tx(config, REC), 20)
    op = process_tx(config, REC, batch_id, 100_000, [("Copper", 100_000)], 0, nonce=5)
    with pytest.raises(ParticipantRuleError, match="suspended"):
        ledger.check(op, block_timestamp=at(minutes=21), height=1, config=config)


def test_recycler_cannot_process_missing_batch(ledger, network) -> None:
    _, config = network
    op = process_tx(config, REC, "ff" * 32, 100, [("Copper", 100)], 0)
    with pytest.raises(ParticipantRuleError, match="existing e-waste batch"):
        ledger.check(op, block_timestamp=at(minutes=20), height=1, config=config)


def test_recycler_cannot_process_recovered_material(ledger, network) -> None:
    _, config = network
    batch_id = _recycler_batch(ledger, network)
    first = _apply(ledger, network, process_tx(config, REC, batch_id, 100_000, [("Copper", 100_000)], 0), 20)
    material_id = f"{first}-0"
    op = process_tx(config, REC, material_id, 100_000, [("Copper", 100_000)], 0, nonce=3)
    with pytest.raises(ParticipantRuleError, match="existing e-waste batch"):
        ledger.check(op, block_timestamp=at(minutes=21), height=1, config=config)


def test_material_processor_cannot_process_batch(ledger, network) -> None:
    _, config = network
    batch_id = _recycler_batch(ledger, network)
    op = process_tx(config, MP, batch_id, 100_000, [("Copper", 100_000)], 0)
    with pytest.raises(ParticipantRuleError, match="recovered material"):
        ledger.check(op, block_timestamp=at(minutes=20), height=1, config=config)


def test_material_processor_cannot_process_missing_material(ledger, network) -> None:
    _, config = network
    op = process_tx(config, MP, "ff" * 32 + "-0", 100, [("Copper", 100)], 0)
    with pytest.raises(ParticipantRuleError, match="recovered material"):
        ledger.check(op, block_timestamp=at(minutes=20), height=1, config=config)


def test_cannot_process_more_than_held(ledger, network) -> None:
    _, config = network
    batch_id = _recycler_batch(ledger, network)
    op = process_tx(config, REC, batch_id, 100_001, [("Copper", 100_001)], 0)
    with pytest.raises(ParticipantRuleError, match="available unreserved inventory"):
        ledger.check(op, block_timestamp=at(minutes=20), height=1, config=config)


@pytest.mark.parametrize(
    ("outputs", "residual"),
    [
        ([("Copper", 60_000)], 0),
        ([("Copper", 60_001)], 40_000),
        ([("Copper", 50_000), ("Plastic", 10_000)], 39_999),
    ],
)
def test_outputs_plus_residual_must_equal_input(ledger, network, outputs, residual) -> None:
    _, config = network
    batch_id = _recycler_batch(ledger, network)
    op = process_tx(config, REC, batch_id, 100_000, outputs, residual)
    with pytest.raises(ParticipantRuleError, match="add up exactly"):
        ledger.check(op, block_timestamp=at(minutes=20), height=1, config=config)


@pytest.mark.parametrize("quantity", [0, -1])
def test_output_quantity_must_be_positive(ledger, network, quantity) -> None:
    _, config = network
    batch_id = _recycler_batch(ledger, network)
    op = process_tx(config, REC, batch_id, 100_000, [("Copper", quantity), ("Plastic", 100_000 - quantity)], 0)
    with pytest.raises(ParticipantRuleError, match="positive whole number of grams"):
        ledger.check(op, block_timestamp=at(minutes=20), height=1, config=config)


@pytest.mark.parametrize("residual", [-1, "5", True, None])
def test_residual_must_be_non_negative_whole_grams(ledger, network, residual) -> None:
    _, config = network
    batch_id = _recycler_batch(ledger, network)
    op = process_tx(config, REC, batch_id, 100_000, [("Copper", 100_000)], residual)
    with pytest.raises(ParticipantRuleError, match="residual quantity"):
        ledger.check(op, block_timestamp=at(minutes=20), height=1, config=config)


def test_zero_residual_is_allowed(ledger, network) -> None:
    _, config = network
    batch_id = _recycler_batch(ledger, network)
    _apply(ledger, network, process_tx(config, REC, batch_id, 100_000, [("Copper", 100_000)], 0), 20)
    assert ledger.business.holding(wallet_pub(REC), batch_id) == 0


def test_output_count_is_bounded(ledger, network) -> None:
    _, config = network
    batch_id = _recycler_batch(ledger, network)
    empty = process_tx(config, REC, batch_id, 100_000, [], 100_000)
    with pytest.raises(ParticipantRuleError, match="between 1 and 20"):
        ledger.check(empty, block_timestamp=at(minutes=20), height=1, config=config)
    too_many = process_tx(config, REC, batch_id, 21, [("Copper", 1)] * 21, 0, nonce=1)
    with pytest.raises(ParticipantRuleError, match="between 1 and 20"):
        ledger.check(too_many, block_timestamp=at(minutes=20), height=1, config=config)


def test_method_length_is_bounded_and_may_be_empty(ledger, network) -> None:
    _, config = network
    batch_id = _recycler_batch(ledger, network)
    long_method = process_tx(config, REC, batch_id, 100, [("Copper", 100)], 0, method="m" * 501)
    with pytest.raises(ParticipantRuleError, match="processing method"):
        ledger.check(long_method, block_timestamp=at(minutes=20), height=1, config=config)
    _apply(ledger, network, process_tx(config, REC, batch_id, 100, [("Copper", 100)], 0, method=""), 20)


def test_duplicate_operation_is_rejected_and_does_not_double_count(ledger, network) -> None:
    _, config = network
    batch_id = _recycler_batch(ledger, network)
    op = process_tx(config, REC, batch_id, 60_000, [("Copper", 60_000)], 0)
    _apply(ledger, network, op, 20)
    with pytest.raises(ParticipantRuleError, match="already been recorded"):
        ledger.check(op, block_timestamp=at(minutes=21), height=1, config=config)
    assert ledger.business.holding(wallet_pub(REC), batch_id) == 40_000


def test_partial_processing_leaves_remainder_and_blocks_overspend(ledger, network) -> None:
    _, config = network
    batch_id = _recycler_batch(ledger, network)
    _apply(ledger, network, process_tx(config, REC, batch_id, 60_000, [("Copper", 60_000)], 0), 20)
    assert ledger.business.holding(wallet_pub(REC), batch_id) == 40_000
    overspend = process_tx(config, REC, batch_id, 40_001, [("Copper", 40_001)], 0, nonce=1)
    with pytest.raises(ParticipantRuleError, match="available unreserved inventory"):
        ledger.check(overspend, block_timestamp=at(minutes=21), height=1, config=config)
    _apply(ledger, network, process_tx(config, REC, batch_id, 40_000, [("Copper", 40_000)], 0, nonce=2), 22)
    assert ledger.business.holding(wallet_pub(REC), batch_id) == 0


def test_material_ids_are_unique_across_outputs_and_operations(ledger, network) -> None:
    _, config = network
    batch_id = _recycler_batch(ledger, network)
    first = _apply(ledger, network, process_tx(config, REC, batch_id, 50_000, [("Copper", 25_000), ("Tin", 25_000)], 0), 20)
    second = _apply(
        ledger, network, process_tx(config, REC, batch_id, 50_000, [("Copper", 50_000)], 0, nonce=1), 21
    )
    ids = [m.material_id for m in ledger.processing.materials()]
    assert ids == [f"{first}-0", f"{first}-1", f"{second}-0"]
    assert len(set(ids)) == len(ids)


def test_residual_and_inputs_are_recorded_on_the_operation(ledger, network) -> None:
    _, config = network
    batch_id = _recycler_batch(ledger, network)
    op = _apply(
        ledger,
        network,
        process_tx(config, REC, batch_id, 100_000, [("Copper", 70_000)], 30_000, method="manual sort"),
        20,
    )
    record = ledger.processing.operation(op)
    assert record.input_item == batch_id
    assert record.input_grams == 100_000
    assert record.residual_grams == 30_000
    assert record.method == "manual sort"
    assert record.output_ids == (f"{op}-0",)


def test_processing_does_not_change_the_original_batch_record(ledger, network) -> None:
    _, config = network
    batch_id = _recycler_batch(ledger, network)
    _apply(ledger, network, process_tx(config, REC, batch_id, 100_000, [("Copper", 100_000)], 0), 20)
    assert ledger.business.batch(batch_id).quantity_grams == 100_000


def test_processing_quantities_must_be_integer_grams(network) -> None:
    _, config = network
    with pytest.raises(ValueError):
        process_tx(config, REC, "ff" * 32, 1.5, [("Copper", 1)], 0)
