from dataclasses import replace
from pathlib import Path

import pytest
from coincurve import PrivateKey

from app.blockchain.mining import open_chain
from app.blockchain.participants import EMAIL_CHANGE_TYPE, REGISTER_TYPE, SUSPEND_TYPE, ParticipantLedger
from app.blockchain.validation import ValidationError
from app.config.shared_network import TrustEpoch
from app.node.attestation import (
    PURPOSE_EMAIL_CHANGE,
    PURPOSE_REGISTRATION,
    attestation_public_key_hex,
    issue_attestation,
    load_attestation_key,
)
from chain_helpers import key_for_label, mine_and_add, shared_network_config, sign_transaction
from node_helpers import create_identities

ISSUED = "2026-01-01T00:00:30Z"


@pytest.fixture
def network(tmp_path: Path):
    identities = create_identities(tmp_path, ["node-a", "node-b"])
    nodes = tuple(
        {"node_id": node_id, "identity": identity, "key": attestation_public_key_hex(load_attestation_key(identity.key_path.parent))}
        for node_id, identity in identities.items()
    )
    from app.config.shared_network import TrustedNode

    listed = tuple(
        TrustedNode(entry["node_id"], entry["identity"].certificate_sha256, entry["key"], "active")
        for entry in nodes
    )
    config = replace(shared_network_config(), trust_epochs=(TrustEpoch(0, 0, listed),))
    return identities, config


def _wallet(label: str) -> tuple[bytes, str]:
    key = key_for_label(label)
    return key, PrivateKey(key).public_key.format(compressed=True).hex()


def _attest(network, wallet_public_key: str, *, purpose=PURPOSE_REGISTRATION, role="Generator", nonce="n1", issued_at=ISSUED, issuer="node-a"):
    identities, config = network
    return issue_attestation(
        identities[issuer].key_path.parent,
        config,
        node_id=issuer,
        purpose=purpose,
        wallet_public_key=wallet_public_key,
        role=role,
        request_id=f"req-{nonce}",
        nonce=nonce,
        issued_at=issued_at,
    )


def _tx(config, label: str, tx_type: str, payload: dict, nonce: int = 0):
    return sign_transaction(config, key_for_label(label), ISSUED, payload=payload, nonce=nonce, tx_type=tx_type)


def _register(network, label: str, *, role="Generator", nonce="n1", issued_at=ISSUED):
    identities, config = network
    _, pub = _wallet(label)
    attestation = _attest(network, pub, role=role, nonce=nonce, issued_at=issued_at)
    return _tx(config, label, REGISTER_TYPE, {"attestation": attestation.to_dict()}, nonce=0)


def _email_change(network, label: str, *, role="Generator", nonce="e1"):
    identities, config = network
    _, pub = _wallet(label)
    attestation = _attest(network, pub, purpose=PURPOSE_EMAIL_CHANGE, role=role, nonce=nonce)
    return _tx(config, label, EMAIL_CHANGE_TYPE, {"attestation": attestation.to_dict()}, nonce=1)


def _block_time(minute: int) -> str:
    return f"2026-01-01T00:{minute:02d}:00Z"


def _grow(store, config, txs, minute: int):
    return mine_and_add(store, config, store.tip, txs, _block_time(minute))


def test_registration_records_role_and_first_email_version(network) -> None:
    _, config = network
    store = open_chain(config)
    _, pub = _wallet("alice")
    _grow(store, config, [_register(network, "alice", role="Recycler")], 1)
    participant = ParticipantLedger.from_blocks(store.canonical_chain, config).participant(pub)
    assert participant is not None
    assert (participant.role, participant.email_version, participant.suspended) == ("Recycler", 1, False)


def test_registration_for_another_wallet_is_rejected(network) -> None:
    _, config = network
    store = open_chain(config)
    _, bob_pub = _wallet("bob")
    attestation = _attest(network, bob_pub)
    forged = _tx(config, "alice", REGISTER_TYPE, {"attestation": attestation.to_dict()})
    with pytest.raises(ValidationError, match="different wallet"):
        _grow(store, config, [forged], 1)


def test_registered_wallet_cannot_register_again_or_change_role(network) -> None:
    _, config = network
    store = open_chain(config)
    _grow(store, config, [_register(network, "alice", role="Generator")], 1)
    with pytest.raises(ValidationError, match="cannot be changed"):
        _grow(store, config, [_register(network, "alice", role="Recycler", nonce="n2")], 2)


def test_registration_attestation_older_than_24_hours_is_rejected(network) -> None:
    _, config = network
    store = open_chain(config)
    with pytest.raises(ValidationError, match="24-hour"):
        _grow(store, config, [_register(network, "alice", issued_at="2025-12-31T00:00:00Z")], 1)


def test_registration_attestation_issued_after_block_is_rejected(network) -> None:
    _, config = network
    store = open_chain(config)
    with pytest.raises(ValidationError, match="24-hour"):
        _grow(store, config, [_register(network, "alice", issued_at="2026-01-01T00:20:00Z")], 1)


def test_email_change_attestation_cannot_register(network) -> None:
    _, config = network
    store = open_chain(config)
    _, pub = _wallet("alice")
    attestation = _attest(network, pub, purpose=PURPOSE_EMAIL_CHANGE)
    with pytest.raises(ValidationError, match="different operation"):
        _grow(store, config, [_tx(config, "alice", REGISTER_TYPE, {"attestation": attestation.to_dict()})], 1)


def test_unknown_role_is_rejected(network) -> None:
    _, config = network
    store = open_chain(config)
    with pytest.raises(ValidationError, match="not recognised"):
        _grow(store, config, [_register(network, "alice", role="Auditor")], 1)


def test_attestation_from_unlisted_issuer_is_rejected(network) -> None:
    identities, config = network
    _, pub = _wallet("alice")
    only_node_a = replace(config, trust_epochs=(replace(config.trust_epochs[0], nodes=config.trust_epochs[0].nodes[:1]),))
    store = open_chain(only_node_a)
    attestation = _attest((identities, only_node_a), pub, issuer="node-b")
    with pytest.raises(ValidationError, match="attestation authority"):
        mine_and_add(
            store,
            only_node_a,
            store.tip,
            [_tx(only_node_a, "alice", REGISTER_TYPE, {"attestation": attestation.to_dict()})],
            _block_time(1),
        )


def test_email_change_increments_version_for_registered_wallet(network) -> None:
    _, config = network
    store = open_chain(config)
    _, pub = _wallet("alice")
    _grow(store, config, [_register(network, "alice")], 1)
    _grow(store, config, [_email_change(network, "alice", nonce="e1")], 2)
    participant = ParticipantLedger.from_blocks(store.canonical_chain, config).participant(pub)
    assert participant.email_version == 2


def test_email_change_attestation_cannot_be_reused(network) -> None:
    _, config = network
    store = open_chain(config)
    _grow(store, config, [_register(network, "alice")], 1)
    change = _email_change(network, "alice", nonce="e1")
    _grow(store, config, [change], 2)
    replay = _tx(config, "alice", EMAIL_CHANGE_TYPE, change.payload, nonce=2)
    with pytest.raises(ValidationError, match="already been used"):
        _grow(store, config, [replay], 3)


def test_email_change_requires_matching_role(network) -> None:
    _, config = network
    store = open_chain(config)
    _grow(store, config, [_register(network, "alice", role="Generator")], 1)
    with pytest.raises(ValidationError, match="does not match"):
        _grow(store, config, [_email_change(network, "alice", role="Recycler")], 2)


def test_email_change_requires_registration(network) -> None:
    _, config = network
    store = open_chain(config)
    with pytest.raises(ValidationError, match="Only a registered wallet"):
        _grow(store, config, [_email_change(network, "alice")], 1)


def test_suspension_blocks_business_transactions_from_that_wallet(network) -> None:
    _, config = network
    store = open_chain(config)
    _grow(store, config, [_register(network, "alice")], 1)
    _grow(store, config, [_tx(config, "alice", SUSPEND_TYPE, {}, nonce=1)], 2)
    with pytest.raises(ValidationError, match="suspended wallet"):
        _grow(store, config, [_tx(config, "alice", "waste.record", {"x": 1}, nonce=2)], 3)


def test_unsuspended_wallet_and_unregistered_wallet_may_send_business_transactions(network) -> None:
    _, config = network
    store = open_chain(config)
    _grow(store, config, [_register(network, "alice"), _tx(config, "bob", "waste.record", {"x": 1})], 1)
    assert len(store.canonical_chain[-1].transactions) == 2


def test_suspended_wallet_cannot_change_email_and_cannot_suspend_twice(network) -> None:
    _, config = network
    store = open_chain(config)
    _grow(store, config, [_register(network, "alice")], 1)
    _grow(store, config, [_tx(config, "alice", SUSPEND_TYPE, {}, nonce=1)], 2)
    with pytest.raises(ValidationError, match="already suspended"):
        _grow(store, config, [_tx(config, "alice", SUSPEND_TYPE, {}, nonce=2)], 3)
    with pytest.raises(ValidationError, match="cannot change its email"):
        _grow(store, config, [_email_change(network, "alice", nonce="e2")], 3)


def test_suspension_requires_registration_and_empty_payload(network) -> None:
    _, config = network
    store = open_chain(config)
    with pytest.raises(ValidationError, match="Only a registered wallet"):
        _grow(store, config, [_tx(config, "alice", SUSPEND_TYPE, {})], 1)
    _grow(store, config, [_register(network, "bob")], 1)
    with pytest.raises(ValidationError, match="unexpected structure"):
        _grow(store, config, [_tx(config, "bob", SUSPEND_TYPE, {"reason": "x"}, nonce=1)], 2)


def test_suspended_wallet_can_register_a_new_wallet(network) -> None:
    _, config = network
    store = open_chain(config)
    _grow(store, config, [_register(network, "alice")], 1)
    _grow(store, config, [_tx(config, "alice", SUSPEND_TYPE, {}, nonce=1)], 2)
    _grow(store, config, [_register(network, "carol", nonce="n3")], 3)
    assert ParticipantLedger.from_blocks(store.canonical_chain, config).participant(_wallet("carol")[1]) is not None
