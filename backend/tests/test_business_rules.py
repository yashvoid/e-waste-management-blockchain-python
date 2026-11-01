import pytest

from app.blockchain.ledger import ChainLedger
from app.blockchain.participants import ParticipantRuleError
from app.blockchain.quantities import kilograms_to_grams
from app.blockchain.structures import parse_utc_timestamp
from business_helpers import (
    COL,
    GEN,
    REC,
    TRA,
    accept_tx,
    apply_block,
    at,
    batch_tx,
    cancel_tx,
    loss_approval,
    make_network,
    register_tx,
    reject_tx,
    request_tx,
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
        ],
        at(minutes=1),
    )
    return ledger


def _create_batch(ledger, network, grams=100_000, *, label=GEN, nonce=0, description="Old laptops"):
    _, config = network
    transaction = batch_tx(config, label, grams, description=description, nonce=nonce)
    apply_block(ledger, config, [transaction], at(minutes=2))
    return transaction.txid


def _request(ledger, network, batch_id, grams, *, sender=GEN, receiver=COL, nonce=0, minute=3):
    _, config = network
    transaction = request_tx(config, sender, batch_id, receiver, grams, nonce=nonce)
    apply_block(ledger, config, [transaction], at(minutes=minute))
    return transaction.txid


def _accept(ledger, network, transfer_id, actual, *, receiver=COL, reason="", approval="", minute=4):
    _, config = network
    transaction = accept_tx(config, receiver, transfer_id, actual, reason=reason, approval=approval)
    apply_block(ledger, config, [transaction], at(minutes=minute))


def _holder_available(ledger, holder, batch_id):
    return ledger.business.available(wallet_pub(holder), batch_id)


def _holding(ledger, holder, batch_id):
    return ledger.business.holding(wallet_pub(holder), batch_id)


def test_generator_creates_batch_with_full_available_quantity(ledger, network) -> None:
    batch_id = _create_batch(ledger, network, 100_000)
    batch = ledger.business.batch(batch_id)
    assert batch is not None
    assert (batch.quantity_grams, batch.description) == (100_000, "Old laptops")
    assert _holder_available(ledger, GEN, batch_id) == 100_000


def test_unregistered_wallet_cannot_create_batch(ledger, network) -> None:
    _, config = network
    with pytest.raises(ParticipantRuleError, match="registered Generator"):
        apply_block(ledger, config, [batch_tx(config, "outsider", 1000)], at(minutes=2))


def test_collector_cannot_create_batch(ledger, network) -> None:
    _, config = network
    with pytest.raises(ParticipantRuleError, match="registered Generator"):
        apply_block(ledger, config, [batch_tx(config, COL, 1000)], at(minutes=2))


def test_suspended_generator_cannot_create_batch(ledger, network) -> None:
    _, config = network
    apply_block(ledger, config, [suspend_tx(config, GEN)], at(minutes=2))
    with pytest.raises(ParticipantRuleError, match="suspended"):
        apply_block(ledger, config, [batch_tx(config, GEN, 1000)], at(minutes=3))


@pytest.mark.parametrize("grams", [0, -1, "100", True])
def test_non_positive_or_non_integer_batch_quantity_rejected(ledger, network, grams) -> None:
    _, config = network
    with pytest.raises(ParticipantRuleError, match="positive whole number of grams"):
        apply_block(ledger, config, [batch_tx(config, GEN, grams)], at(minutes=2))


@pytest.mark.parametrize("description", ["", "   ", "x" * 501, 42])
def test_invalid_batch_description_rejected(ledger, network, description) -> None:
    _, config = network
    with pytest.raises(ParticipantRuleError, match="description"):
        apply_block(ledger, config, [batch_tx(config, GEN, 1000, description=description)], at(minutes=2))


@pytest.mark.parametrize(
    ("text", "grams"),
    [("100", 100_000), ("95.5", 95_500), ("0.001", 1), ("2.250", 2_250), ("0.5", 500), ("007", 7_000)],
)
def test_kilograms_convert_to_integer_grams(text, grams) -> None:
    assert kilograms_to_grams(text) == grams


@pytest.mark.parametrize("text", ["1.0001", "-1", "1e3", "", " 5", "1,5", "1.", ".5", None, 5])
def test_invalid_kilogram_input_rejected(text) -> None:
    with pytest.raises(ValueError):
        kilograms_to_grams(text)


def test_generator_to_collector_transfer_reserves_declared_quantity(ledger, network) -> None:
    batch_id = _create_batch(ledger, network)
    _request(ledger, network, batch_id, 40_000)
    assert ledger.business.reserved(wallet_pub(GEN), batch_id) == 40_000
    assert _holder_available(ledger, GEN, batch_id) == 60_000
    assert _holding(ledger, GEN, batch_id) == 100_000


def test_collector_to_transporter_transfer_is_valid(ledger, network) -> None:
    batch_id = _create_batch(ledger, network)
    transfer_id = _request(ledger, network, batch_id, 100_000)
    _accept(ledger, network, transfer_id, 100_000)
    second_id = _request(ledger, network, batch_id, 50_000, sender=COL, receiver=TRA, nonce=1)
    assert ledger.business.transfer(second_id).status == "pending"


def test_transporter_to_recycler_transfer_is_valid(ledger, network) -> None:
    batch_id = _create_batch(ledger, network)
    first = _request(ledger, network, batch_id, 100_000)
    _accept(ledger, network, first, 100_000)
    second = _request(ledger, network, batch_id, 100_000, sender=COL, receiver=TRA, nonce=1, minute=5)
    _accept(ledger, network, second, 100_000, receiver=TRA, minute=6)
    third = _request(ledger, network, batch_id, 100_000, sender=TRA, receiver=REC, nonce=2, minute=7)
    assert ledger.business.transfer(third).receiver == wallet_pub(REC)


def test_invalid_role_transition_rejected(ledger, network) -> None:
    _, config = network
    batch_id = _create_batch(ledger, network)
    with pytest.raises(ParticipantRuleError, match="can only transfer to a Collector"):
        apply_block(ledger, config, [request_tx(config, GEN, batch_id, TRA, 1000)], at(minutes=3))


def test_skipping_a_role_rejected(ledger, network) -> None:
    _, config = network
    batch_id = _create_batch(ledger, network)
    with pytest.raises(ParticipantRuleError, match="can only transfer to a Collector"):
        apply_block(ledger, config, [request_tx(config, GEN, batch_id, REC, 1000)], at(minutes=3))


def test_self_transfer_rejected(ledger, network) -> None:
    _, config = network
    batch_id = _create_batch(ledger, network)
    with pytest.raises(ParticipantRuleError, match="themselves"):
        apply_block(ledger, config, [request_tx(config, GEN, batch_id, GEN, 1000)], at(minutes=3))


def test_unregistered_receiver_rejected(ledger, network) -> None:
    _, config = network
    batch_id = _create_batch(ledger, network)
    with pytest.raises(ParticipantRuleError, match="registered, active"):
        apply_block(ledger, config, [request_tx(config, GEN, batch_id, "stranger", 1000)], at(minutes=3))


def test_suspended_receiver_rejected(ledger, network) -> None:
    _, config = network
    batch_id = _create_batch(ledger, network)
    apply_block(ledger, config, [suspend_tx(config, COL)], at(minutes=2, seconds=30))
    with pytest.raises(ParticipantRuleError, match="registered, active"):
        apply_block(ledger, config, [request_tx(config, GEN, batch_id, COL, 1000)], at(minutes=3))


def test_suspended_sender_cannot_request_transfer(ledger, network) -> None:
    _, config = network
    batch_id = _create_batch(ledger, network)
    apply_block(ledger, config, [suspend_tx(config, GEN)], at(minutes=2, seconds=30))
    with pytest.raises(ParticipantRuleError, match="suspended"):
        apply_block(ledger, config, [request_tx(config, GEN, batch_id, COL, 1000)], at(minutes=3))


def test_quantity_above_available_rejected(ledger, network) -> None:
    _, config = network
    batch_id = _create_batch(ledger, network, 100_000)
    with pytest.raises(ParticipantRuleError, match="available unreserved"):
        apply_block(ledger, config, [request_tx(config, GEN, batch_id, COL, 100_001)], at(minutes=3))


def test_multiple_reservations_within_available_are_accepted(ledger, network) -> None:
    batch_id = _create_batch(ledger, network, 100_000)
    _request(ledger, network, batch_id, 30_000, nonce=0)
    _request(ledger, network, batch_id, 70_000, nonce=1, minute=4)
    assert ledger.business.reserved(wallet_pub(GEN), batch_id) == 100_000
    assert _holder_available(ledger, GEN, batch_id) == 0


def test_over_reservation_rejected(ledger, network) -> None:
    _, config = network
    batch_id = _create_batch(ledger, network, 100_000)
    _request(ledger, network, batch_id, 60_000, nonce=0)
    with pytest.raises(ParticipantRuleError, match="available unreserved"):
        apply_block(ledger, config, [request_tx(config, GEN, batch_id, COL, 50_000, nonce=1)], at(minutes=4))
    assert ledger.business.reserved(wallet_pub(GEN), batch_id) == 60_000


def test_recycler_cannot_start_a_transfer_in_this_stage(ledger, network) -> None:
    _, config = network
    batch_id = _create_batch(ledger, network)
    with pytest.raises(ParticipantRuleError, match="A Recycler can only transfer recovered material"):
        apply_block(ledger, config, [request_tx(config, REC, batch_id, COL, 1000)], at(minutes=3))


def test_holder_without_inventory_cannot_transfer(ledger, network) -> None:
    _, config = network
    batch_id = _create_batch(ledger, network)
    with pytest.raises(ParticipantRuleError, match="available unreserved"):
        apply_block(ledger, config, [request_tx(config, COL, batch_id, TRA, 1000)], at(minutes=3))


@pytest.mark.parametrize("grams", [0, -5, "5"])
def test_non_positive_transfer_quantity_rejected(ledger, network, grams) -> None:
    _, config = network
    batch_id = _create_batch(ledger, network)
    with pytest.raises(ParticipantRuleError, match="positive whole number of grams"):
        apply_block(ledger, config, [request_tx(config, GEN, batch_id, COL, grams)], at(minutes=3))


def test_full_acceptance_moves_quantity_to_receiver(ledger, network) -> None:
    batch_id = _create_batch(ledger, network, 100_000)
    transfer_id = _request(ledger, network, batch_id, 100_000)
    _accept(ledger, network, transfer_id, 100_000)
    assert _holding(ledger, GEN, batch_id) == 0
    assert _holding(ledger, COL, batch_id) == 100_000
    assert ledger.business.transfer(transfer_id).status == "accepted"


def test_partial_acceptance_records_discrepancy(ledger, network) -> None:
    batch_id = _create_batch(ledger, network, 100_000)
    transfer_id = _request(ledger, network, batch_id, 100_000)
    _accept(ledger, network, transfer_id, 95_000, reason="Damaged in transit")
    assert _holding(ledger, GEN, batch_id) == 0
    assert _holding(ledger, COL, batch_id) == 95_000
    assert ledger.business.discrepancy(batch_id) == 5_000
    assert ledger.business.transfer(transfer_id).reason == "Damaged in transit"


def test_lower_quantity_without_reason_rejected(ledger, network) -> None:
    _, config = network
    batch_id = _create_batch(ledger, network, 100_000)
    transfer_id = _request(ledger, network, batch_id, 100_000)
    with pytest.raises(ParticipantRuleError, match="discrepancy reason"):
        apply_block(ledger, config, [accept_tx(config, COL, transfer_id, 95_000)], at(minutes=4))


def test_actual_quantity_above_declared_rejected(ledger, network) -> None:
    _, config = network
    batch_id = _create_batch(ledger, network, 100_000)
    transfer_id = _request(ledger, network, batch_id, 50_000)
    with pytest.raises(ParticipantRuleError, match="cannot exceed"):
        apply_block(ledger, config, [accept_tx(config, COL, transfer_id, 50_001)], at(minutes=4))


def test_zero_receipt_without_sender_approval_rejected(ledger, network) -> None:
    _, config = network
    batch_id = _create_batch(ledger, network, 100_000)
    transfer_id = _request(ledger, network, batch_id, 100_000)
    with pytest.raises(ParticipantRuleError, match="approval signature"):
        apply_block(
            ledger,
            config,
            [accept_tx(config, COL, transfer_id, 0, reason="Lost in transit")],
            at(minutes=4),
        )


def test_zero_receipt_with_wrong_signer_approval_rejected(ledger, network) -> None:
    _, config = network
    batch_id = _create_batch(ledger, network, 100_000)
    transfer_id = _request(ledger, network, batch_id, 100_000)
    wrong = loss_approval(COL, transfer_id, "Lost in transit")
    with pytest.raises(ParticipantRuleError, match="approval signature"):
        apply_block(
            ledger,
            config,
            [accept_tx(config, COL, transfer_id, 0, reason="Lost in transit", approval=wrong)],
            at(minutes=4),
        )


def test_zero_receipt_with_sender_approval_is_recorded(ledger, network) -> None:
    _, config = network
    batch_id = _create_batch(ledger, network, 100_000)
    transfer_id = _request(ledger, network, batch_id, 100_000)
    approval = loss_approval(GEN, transfer_id, "Lost in transit")
    _accept(ledger, network, transfer_id, 0, reason="Lost in transit", approval=approval)
    assert _holding(ledger, GEN, batch_id) == 0
    assert _holding(ledger, COL, batch_id) == 0
    assert ledger.business.discrepancy(batch_id) == 100_000


def test_only_designated_receiver_can_accept(ledger, network) -> None:
    _, config = network
    batch_id = _create_batch(ledger, network)
    transfer_id = _request(ledger, network, batch_id, 100_000)
    with pytest.raises(ParticipantRuleError, match="designated receiver"):
        apply_block(ledger, config, [accept_tx(config, GEN, transfer_id, 100_000)], at(minutes=4))


def test_duplicate_acceptance_rejected(ledger, network) -> None:
    _, config = network
    batch_id = _create_batch(ledger, network)
    transfer_id = _request(ledger, network, batch_id, 100_000)
    _accept(ledger, network, transfer_id, 100_000)
    with pytest.raises(ParticipantRuleError, match="no longer pending"):
        apply_block(ledger, config, [accept_tx(config, COL, transfer_id, 100_000, nonce=1)], at(minutes=5))


def test_rejection_requires_reason(ledger, network) -> None:
    _, config = network
    batch_id = _create_batch(ledger, network)
    transfer_id = _request(ledger, network, batch_id, 100_000)
    with pytest.raises(ParticipantRuleError, match="rejection reason"):
        apply_block(ledger, config, [reject_tx(config, COL, transfer_id, "")], at(minutes=4))


def test_only_designated_receiver_can_reject(ledger, network) -> None:
    _, config = network
    batch_id = _create_batch(ledger, network)
    transfer_id = _request(ledger, network, batch_id, 100_000)
    with pytest.raises(ParticipantRuleError, match="designated receiver"):
        apply_block(ledger, config, [reject_tx(config, GEN, transfer_id, "Not mine")], at(minutes=4))


def test_rejection_releases_reservation_without_moving_ownership(ledger, network) -> None:
    _, config = network
    batch_id = _create_batch(ledger, network)
    transfer_id = _request(ledger, network, batch_id, 100_000)
    apply_block(ledger, config, [reject_tx(config, COL, transfer_id, "Wrong batch")], at(minutes=4))
    assert ledger.business.transfer(transfer_id).status == "rejected"
    assert _holder_available(ledger, GEN, batch_id) == 100_000
    assert _holding(ledger, GEN, batch_id) == 100_000
    assert _holding(ledger, COL, batch_id) == 0


def test_only_original_sender_can_cancel(ledger, network) -> None:
    _, config = network
    batch_id = _create_batch(ledger, network)
    transfer_id = _request(ledger, network, batch_id, 100_000)
    with pytest.raises(ParticipantRuleError, match="original sender"):
        apply_block(ledger, config, [cancel_tx(config, COL, transfer_id)], at(minutes=4))


def test_cancellation_releases_reservation(ledger, network) -> None:
    _, config = network
    batch_id = _create_batch(ledger, network)
    transfer_id = _request(ledger, network, batch_id, 100_000)
    apply_block(ledger, config, [cancel_tx(config, GEN, transfer_id)], at(minutes=4))
    assert ledger.business.transfer(transfer_id).status == "cancelled"
    assert _holder_available(ledger, GEN, batch_id) == 100_000


def test_cancellation_after_acceptance_rejected(ledger, network) -> None:
    _, config = network
    batch_id = _create_batch(ledger, network)
    transfer_id = _request(ledger, network, batch_id, 100_000)
    _accept(ledger, network, transfer_id, 100_000)
    with pytest.raises(ParticipantRuleError, match="no longer pending"):
        apply_block(ledger, config, [cancel_tx(config, GEN, transfer_id, nonce=1)], at(minutes=5))


@pytest.mark.parametrize("ending", ["reject", "cancel"])
def test_response_after_rejection_or_cancellation_rejected(ledger, network, ending) -> None:
    _, config = network
    batch_id = _create_batch(ledger, network)
    transfer_id = _request(ledger, network, batch_id, 100_000)
    closing = (
        reject_tx(config, COL, transfer_id, "Not needed")
        if ending == "reject"
        else cancel_tx(config, GEN, transfer_id)
    )
    apply_block(ledger, config, [closing], at(minutes=4))
    with pytest.raises(ParticipantRuleError, match="no longer pending"):
        apply_block(ledger, config, [accept_tx(config, COL, transfer_id, 100_000, nonce=1)], at(minutes=5))


def test_transfer_remains_pending_before_expiry(ledger, network) -> None:
    _, config = network
    batch_id = _create_batch(ledger, network)
    transfer_id = _request(ledger, network, batch_id, 100_000)
    apply_block(ledger, config, [], at(minutes=3, hours=48, seconds=-1))
    assert ledger.business.transfer(transfer_id).status == "pending"


def test_transfer_expires_at_boundary_and_releases_reservation(ledger, network) -> None:
    _, config = network
    batch_id = _create_batch(ledger, network)
    transfer_id = _request(ledger, network, batch_id, 100_000)
    assert ledger.business.transfer(transfer_id).expires_at == parse_utc_timestamp(at(minutes=3, hours=48))
    apply_block(ledger, config, [], at(minutes=3, hours=48))
    assert ledger.business.transfer(transfer_id).status == "expired"
    assert _holder_available(ledger, GEN, batch_id) == 100_000


def test_late_acceptance_rejected(ledger, network) -> None:
    _, config = network
    batch_id = _create_batch(ledger, network)
    transfer_id = _request(ledger, network, batch_id, 100_000)
    with pytest.raises(ParticipantRuleError, match="no longer pending|expired"):
        apply_block(ledger, config, [accept_tx(config, COL, transfer_id, 100_000)], at(minutes=3, hours=48))


def test_no_quantity_silently_disappears(ledger, network) -> None:
    batch_id = _create_batch(ledger, network, 100_000)
    transfer_id = _request(ledger, network, batch_id, 100_000)
    _accept(ledger, network, transfer_id, 95_000, reason="Damaged in transit")
    created = ledger.business.batch(batch_id).quantity_grams
    held = _holding(ledger, GEN, batch_id) + _holding(ledger, COL, batch_id)
    assert held + ledger.business.discrepancy(batch_id) == created

