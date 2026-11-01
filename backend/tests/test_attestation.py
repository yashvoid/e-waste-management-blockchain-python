from dataclasses import replace
from pathlib import Path

import pytest
from coincurve import PrivateKey
from cryptography.hazmat.primitives import serialization

from app.config.errors import ConfigurationError
from app.config.shared_network import SharedNetworkConfig, TrustedNode, TrustEpoch
from app.node.attestation import (
    ATTESTATION_KEY_FILE_NAME,
    PURPOSE_EMAIL_CHANGE,
    PURPOSE_REGISTRATION,
    Attestation,
    AttestationError,
    attestation_from_dict,
    attestation_public_key_hex,
    issue_attestation,
    load_attestation_key,
    provision_attestation_key,
    require_listed_attestation_key,
    verify_attestation,
)
from app.node.identity import KEY_FILE_NAME
from chain_helpers import shared_network_config
from node_helpers import create_identities

ISSUED_AT = "2026-11-01T10:00:00Z"
WALLET = PrivateKey(bytes([7] * 32)).public_key.format(compressed=True).hex()


@pytest.fixture
def authority(tmp_path: Path):
    identities = create_identities(tmp_path, ["node-a", "node-b"])
    keys = {
        node_id: attestation_public_key_hex(load_attestation_key(identity.key_path.parent))
        for node_id, identity in identities.items()
    }
    nodes = tuple(
        TrustedNode(node_id, identity.certificate_sha256, keys[node_id], "active")
        for node_id, identity in identities.items()
    )
    base = shared_network_config()
    config = replace(base, trust_epochs=(TrustEpoch(0, 0, nodes),))
    return identities, config


def _issue(identities, config, *, purpose=PURPOSE_REGISTRATION, role="collector", wallet=WALLET) -> Attestation:
    return issue_attestation(
        identities["node-a"].key_path.parent,
        config,
        node_id="node-a",
        purpose=purpose,
        wallet_public_key=wallet,
        role=role,
        request_id="req-1",
        nonce="nonce-1",
        issued_at=ISSUED_AT,
    )


def test_issued_attestation_verifies(authority) -> None:
    identities, config = authority
    attestation = _issue(identities, config)
    verify_attestation(attestation, config=config, expected_purpose=PURPOSE_REGISTRATION, chain_height=0)


def test_registration_attestation_cannot_be_used_for_email_change(authority) -> None:
    identities, config = authority
    attestation = _issue(identities, config)
    with pytest.raises(AttestationError, match="different operation"):
        verify_attestation(attestation, config=config, expected_purpose=PURPOSE_EMAIL_CHANGE, chain_height=0)


@pytest.mark.parametrize("change", [{"role": "recycler"}, {"wallet_public_key": "02" + "11" * 32}, {"nonce": "other"}])
def test_altered_attestation_body_is_rejected(authority, change: dict) -> None:
    identities, config = authority
    attestation = replace(_issue(identities, config), **change)
    with pytest.raises(AttestationError):
        verify_attestation(attestation, config=config, expected_purpose=PURPOSE_REGISTRATION, chain_height=0)


def test_attestation_for_another_network_is_rejected(authority) -> None:
    identities, config = authority
    attestation = replace(_issue(identities, config), network_id="other-network")
    with pytest.raises(AttestationError, match="different network"):
        verify_attestation(attestation, config=config, expected_purpose=PURPOSE_REGISTRATION, chain_height=0)


def test_attestation_from_unlisted_issuer_is_rejected(authority) -> None:
    identities, config = authority
    attestation = replace(_issue(identities, config), issuer_node_id="node-z")
    with pytest.raises(AttestationError):
        verify_attestation(attestation, config=config, expected_purpose=PURPOSE_REGISTRATION, chain_height=0)


def test_attestation_is_not_accepted_before_its_epoch_activates(authority) -> None:
    identities, config = authority
    later = replace(config, trust_epochs=(config.trust_epochs[0], TrustEpoch(1, 100, config.trust_epochs[0].nodes)))
    attestation = replace(_issue(identities, later), epoch=1)
    with pytest.raises(AttestationError, match="not yet active"):
        verify_attestation(attestation, config=later, expected_purpose=PURPOSE_REGISTRATION, chain_height=50)


def test_revoked_issuer_is_refused_from_its_revocation_height(authority) -> None:
    identities, config = authority
    node_a = config.trust_epochs[0].nodes[0]
    revoked_nodes = (replace(node_a, status="revoked"), config.trust_epochs[0].nodes[1])
    revoked = replace(config, trust_epochs=(config.trust_epochs[0], TrustEpoch(1, 20, revoked_nodes)))
    attestation = _issue(identities, config)
    with pytest.raises(AttestationError, match="not an active attestation authority"):
        verify_attestation(attestation, config=revoked, expected_purpose=PURPOSE_REGISTRATION, chain_height=20)


def test_invalid_wallet_key_is_refused_when_issuing(authority) -> None:
    identities, config = authority
    with pytest.raises(AttestationError, match="wallet key"):
        _issue(identities, config, wallet="not-a-key")


def test_attestation_key_is_separate_from_tls_key(tmp_path: Path) -> None:
    identities = create_identities(tmp_path, ["node-a"])
    identity_dir = identities["node-a"].key_path.parent
    tls_key_bytes = (identity_dir / KEY_FILE_NAME).read_bytes()
    assert tls_key_bytes != (identity_dir / ATTESTATION_KEY_FILE_NAME).read_bytes()
    tls_key = serialization.load_pem_private_key(tls_key_bytes, password=None)
    tls_public = tls_key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.CompressedPoint)
    assert tls_public.hex() != attestation_public_key_hex(load_attestation_key(identity_dir))


def test_attestation_key_is_never_replaced(tmp_path: Path) -> None:
    identity_dir = tmp_path / "identity"
    identity_dir.mkdir()
    provision_attestation_key(identity_dir)
    before = (identity_dir / ATTESTATION_KEY_FILE_NAME).read_bytes()
    with pytest.raises(ConfigurationError, match="never replaced"):
        provision_attestation_key(identity_dir)
    assert (identity_dir / ATTESTATION_KEY_FILE_NAME).read_bytes() == before


def test_listed_attestation_key_is_required_at_startup(authority) -> None:
    identities, config = authority
    identity_dir = identities["node-a"].key_path.parent
    require_listed_attestation_key(identity_dir, config, "node-a")

    other = replace(config, trust_epochs=(TrustEpoch(0, 0, (replace(config.trust_epochs[0].nodes[0], attestation_public_key="03" + "22" * 32),)),))
    with pytest.raises(ConfigurationError, match="not an active entry"):
        require_listed_attestation_key(identity_dir, other, "node-a")


@pytest.mark.parametrize(
    "value",
    [
        "not a dict",
        {"network_id": "x"},
        {"epoch": "0"},
    ],
)
def test_malformed_attestation_is_rejected(value: object) -> None:
    with pytest.raises(AttestationError):
        attestation_from_dict(value)


def test_attestation_round_trips_through_dict(authority) -> None:
    identities, config = authority
    attestation = _issue(identities, config)
    assert attestation_from_dict(attestation.to_dict()) == attestation
