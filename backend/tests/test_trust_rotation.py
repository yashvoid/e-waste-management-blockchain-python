from dataclasses import replace
from pathlib import Path

import pytest
from coincurve import PrivateKey

from app.config.errors import ConfigurationError
from app.config.shared_network import TrustedNode, TrustEpoch, epoch_in_force, trust_configuration_hash
from app.node.attestation import (
    PURPOSE_REGISTRATION,
    AttestationError,
    attestation_public_key_hex,
    issue_attestation,
    load_attestation_key,
    verify_attestation,
)
from app.node.peer_client import PeerHello, incompatibility
from app.node.peer_trust import import_peer_certificate
from chain_helpers import shared_network_config
from node_helpers import create_identities

ISSUED_AT = "2026-11-01T10:00:00Z"
WALLET = PrivateKey(bytes([9] * 32)).public_key.format(compressed=True).hex()
ROTATION_HEIGHT = 100
REVOCATION_HEIGHT = 200


def _node(identities, node_id: str, status: str) -> TrustedNode:
    identity = identities[node_id]
    return TrustedNode(
        node_id,
        identity.certificate_sha256,
        attestation_public_key_hex(load_attestation_key(identity.key_path.parent)),
        status,
    )


@pytest.fixture
def network(tmp_path: Path):
    original = create_identities(tmp_path / "original", ["node-a", "node-b"])
    rotated = create_identities(tmp_path / "rotated", ["node-a"])
    base = shared_network_config()
    epoch0 = (_node(original, "node-a", "active"), _node(original, "node-b", "active"))
    epoch1 = (
        _node(original, "node-a", "retired"),
        _node(rotated, "node-a", "active"),
        _node(original, "node-b", "active"),
    )
    single = replace(base, trust_epochs=(TrustEpoch(0, 0, epoch0),))
    rotated_config = replace(
        base,
        trust_epochs=(TrustEpoch(0, 0, epoch0), TrustEpoch(1, ROTATION_HEIGHT, epoch1)),
    )
    return {"original": original, "rotated": rotated, "single": single, "rotated_config": rotated_config}


def _issue(identity_dir: Path, config, node_id: str = "node-a") -> object:
    return issue_attestation(
        identity_dir,
        config,
        node_id=node_id,
        purpose=PURPOSE_REGISTRATION,
        wallet_public_key=WALLET,
        role="Collector",
        request_id="req-1",
        nonce="nonce-1",
        issued_at=ISSUED_AT,
    )


def test_epoch_in_force_switches_at_activation_height(network) -> None:
    config = network["rotated_config"]
    assert epoch_in_force(config, ROTATION_HEIGHT - 1).epoch == 0
    assert epoch_in_force(config, ROTATION_HEIGHT).epoch == 1


def test_attestation_from_old_key_verifies_before_rotation(network) -> None:
    old_dir = network["original"]["node-a"].key_path.parent
    attestation = _issue(old_dir, network["single"])
    verify_attestation(attestation, config=network["rotated_config"], expected_purpose=PURPOSE_REGISTRATION, chain_height=ROTATION_HEIGHT - 1)


def test_old_key_is_refused_for_attestations_included_after_retirement(network) -> None:
    old_dir = network["original"]["node-a"].key_path.parent
    attestation = _issue(old_dir, network["single"])
    with pytest.raises(AttestationError, match="not an active attestation authority"):
        verify_attestation(attestation, config=network["rotated_config"], expected_purpose=PURPOSE_REGISTRATION, chain_height=ROTATION_HEIGHT)


def test_new_key_attestation_verifies_after_rotation(network) -> None:
    new_dir = network["rotated"]["node-a"].key_path.parent
    attestation = _issue(new_dir, network["rotated_config"])
    assert attestation.epoch == 1
    verify_attestation(attestation, config=network["rotated_config"], expected_purpose=PURPOSE_REGISTRATION, chain_height=ROTATION_HEIGHT)


def test_attestation_naming_an_unknown_epoch_is_rejected(network) -> None:
    attestation = _issue(network["original"]["node-a"].key_path.parent, network["single"])
    with pytest.raises(AttestationError, match="unknown trust epoch"):
        verify_attestation(
            replace(attestation, epoch=7),
            config=network["rotated_config"],
            expected_purpose=PURPOSE_REGISTRATION,
            chain_height=ROTATION_HEIGHT,
        )


def test_revoked_key_remains_valid_for_attestations_before_revocation(network) -> None:
    base = network["rotated_config"]
    epoch1 = base.trust_epochs[1]
    revoked_nodes = tuple(
        replace(node, status="revoked") if node.node_id == "node-a" and node.status == "active" else node
        for node in epoch1.nodes
    )
    revoked = replace(base, trust_epochs=(base.trust_epochs[0], epoch1, TrustEpoch(2, REVOCATION_HEIGHT, revoked_nodes)))
    attestation = _issue(network["rotated"]["node-a"].key_path.parent, network["rotated_config"])
    verify_attestation(attestation, config=revoked, expected_purpose=PURPOSE_REGISTRATION, chain_height=REVOCATION_HEIGHT - 1)
    with pytest.raises(AttestationError, match="not an active attestation authority"):
        verify_attestation(attestation, config=revoked, expected_purpose=PURPOSE_REGISTRATION, chain_height=REVOCATION_HEIGHT)


def test_trust_configuration_hash_is_stable_and_detects_changes(network) -> None:
    config = network["rotated_config"]
    assert trust_configuration_hash(config) == trust_configuration_hash(network["rotated_config"])
    assert trust_configuration_hash(config) != trust_configuration_hash(network["single"])
    epoch1 = config.trust_epochs[1]
    altered_nodes = (epoch1.nodes[0], epoch1.nodes[1], replace(epoch1.nodes[2], status="retired"))
    altered = replace(config, trust_epochs=(config.trust_epochs[0], TrustEpoch(1, ROTATION_HEIGHT, altered_nodes)))
    assert trust_configuration_hash(config) != trust_configuration_hash(altered)


def _hello(config, *, trust_hash: str | None = None) -> PeerHello:
    return PeerHello(
        node_id="node-a",
        network_id=config.network_id,
        protocol_version=config.protocol_version,
        genesis_hash=config.genesis_hash,
        trust_config_hash=trust_hash or trust_configuration_hash(config),
    )


def test_peer_with_matching_trust_configuration_is_accepted(network) -> None:
    config = network["rotated_config"]
    assert incompatibility(_hello(config), "node-a", config) is None


def test_peer_with_different_trust_configuration_is_refused(network) -> None:
    config = network["rotated_config"]
    other = trust_configuration_hash(network["single"])
    problem = incompatibility(_hello(config, trust_hash=other), "node-a", config)
    assert problem is not None and "trust configuration" in problem


def test_certificate_with_unlisted_fingerprint_is_refused_on_import(network, tmp_path: Path) -> None:
    stranger = create_identities(tmp_path / "stranger", ["node-z"])["node-z"]
    identity_dir = network["original"]["node-b"].certificate_path.parent
    with pytest.raises(ConfigurationError, match="not listed"):
        import_peer_certificate(identity_dir, network["single"], stranger.certificate_path)


def test_peer_claiming_a_different_node_is_still_refused(network) -> None:

    config = network["rotated_config"]
    assert incompatibility(_hello(config), "node-b", config) == "The peer identifies itself as a different node."
