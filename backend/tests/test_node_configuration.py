import json
from pathlib import Path

import pytest

from app.config.errors import ConfigurationError
from app.config.node_settings import PEERS_ENV, PeerAddress, load_node_settings
from app.config.shared_network import epoch_in_force, load_shared_network_config
from chain_helpers import attestation_key_hex, shared_network_values

FINGERPRINT_A = "a" * 64
FINGERPRINT_B = "b" * 64
FINGERPRINT_C = "c" * 64


def _node(node_id: str, fingerprint: str, status: str = "active", key_label: str | None = None) -> dict[str, str]:
    return {
        "node_id": node_id,
        "tls_certificate_sha256": fingerprint,
        "attestation_public_key": attestation_key_hex(key_label or f"{node_id}-{fingerprint[:4]}"),
        "status": status,
    }


def _epoch(number: int, activation_height: int, nodes: list[dict[str, str]]) -> dict[str, object]:
    return {"epoch": number, "activation_height": activation_height, "nodes": nodes}


def _write_shared(tmp_path: Path, trust_epochs: object) -> Path:
    values = shared_network_values()
    values["trust_epochs"] = trust_epochs
    path = tmp_path / "shared.json"
    path.write_text(json.dumps(values), encoding="utf-8")
    return path


def test_peers_are_parsed_from_environment(node_environ: dict[str, str]) -> None:
    node_environ[PEERS_ENV] = "node-b@192.168.1.20:8443, node-c@192.168.1.30:8443"
    settings = load_node_settings(node_environ)
    assert settings.peers == (
        PeerAddress(node_id="node-b", host="192.168.1.20", port=8443),
        PeerAddress(node_id="node-c", host="192.168.1.30", port=8443),
    )


@pytest.mark.parametrize(
    "peers",
    ["node-b:8443", "node-b@host", "Node-B@host:8443", "test-node@host:8443", "node-b@host:70000", "node-b@h:1,node-b@g:2"],
)
def test_invalid_peer_entries_are_rejected(node_environ: dict[str, str], peers: str) -> None:
    node_environ[PEERS_ENV] = peers
    with pytest.raises(ConfigurationError):
        load_node_settings(node_environ)


def test_peer_port_is_required(node_environ: dict[str, str]) -> None:
    del node_environ["EWASTE_PEER_PORT"]
    with pytest.raises(ConfigurationError, match="EWASTE_PEER_PORT"):
        load_node_settings(node_environ)


def test_trust_epochs_are_loaded_in_order(tmp_path: Path) -> None:
    path = _write_shared(
        tmp_path,
        [
            _epoch(0, 0, [_node("node-a", FINGERPRINT_A), _node("node-b", FINGERPRINT_B)]),
            _epoch(1, 50, [_node("node-a", FINGERPRINT_A), _node("node-b", FINGERPRINT_B)]),
        ],
    )
    config = load_shared_network_config(path)
    assert [(epoch.epoch, epoch.activation_height) for epoch in config.trust_epochs] == [(0, 0), (1, 50)]
    assert [node.node_id for node in config.trust_epochs[0].nodes] == ["node-a", "node-b"]


def test_epoch_in_force_follows_activation_height(tmp_path: Path) -> None:
    path = _write_shared(
        tmp_path,
        [
            _epoch(0, 0, [_node("node-a", FINGERPRINT_A)]),
            _epoch(1, 10, [_node("node-a", FINGERPRINT_B)]),
        ],
    )
    config = load_shared_network_config(path)
    assert epoch_in_force(config, 0).epoch == 0
    assert epoch_in_force(config, 9).epoch == 0
    assert epoch_in_force(config, 10).epoch == 1


def test_renewal_overlap_lists_retired_and_active_certificates(tmp_path: Path) -> None:
    path = _write_shared(
        tmp_path,
        [
            _epoch(0, 0, [_node("node-a", FINGERPRINT_A)]),
            _epoch(
                1,
                20,
                [_node("node-a", FINGERPRINT_A, status="retired"), _node("node-a", FINGERPRINT_B)],
            ),
        ],
    )
    config = load_shared_network_config(path)
    assert [node.tls_certificate_sha256 for node in config.trust_epochs[1].nodes] == [FINGERPRINT_A, FINGERPRINT_B]


@pytest.mark.parametrize(
    "trust_epochs",
    [
        "node-a",
        [],
        [_epoch(1, 0, [_node("node-a", FINGERPRINT_A)])],
        [_epoch(0, 5, [_node("node-a", FINGERPRINT_A)])],
        [_epoch(0, 0, [_node("node-a", FINGERPRINT_A)]), _epoch(1, 0, [_node("node-a", FINGERPRINT_B)])],
        [_epoch(0, 0, [_node("node-a", FINGERPRINT_A)]), _epoch(2, 10, [_node("node-a", FINGERPRINT_B)])],
        [_epoch(0, 0, [])],
        [_epoch(0, 0, [{"node_id": "node-a"}])],
        [_epoch(0, 0, [_node("Node-A", FINGERPRINT_A)])],
        [_epoch(0, 0, [_node("node-a", "ABC")])],
        [_epoch(0, 0, [_node("node-a", FINGERPRINT_A, status="pending")])],
        [_epoch(0, 0, [_node("node-a", FINGERPRINT_A), _node("node-a", FINGERPRINT_B)])],
        [_epoch(0, 0, [_node("node-a", FINGERPRINT_A), _node("node-b", FINGERPRINT_A)])],
        [_epoch(0, 0, [_node("node-a", FINGERPRINT_A, key_label="same"), _node("node-b", FINGERPRINT_B, key_label="same")])],
        [_epoch(0, 0, [_node("node-a", FINGERPRINT_A, status="retired")])],
        [
            _epoch(0, 0, [_node("node-a", FINGERPRINT_A)]),
            _epoch(1, 10, [_node("node-a", FINGERPRINT_B, status="revoked")]),
            _epoch(2, 20, [_node("node-a", FINGERPRINT_C)]),
        ],
    ],
)
def test_invalid_trust_epochs_are_rejected(tmp_path: Path, trust_epochs: object) -> None:
    with pytest.raises(ConfigurationError):
        load_shared_network_config(_write_shared(tmp_path, trust_epochs))


def test_old_flat_trusted_nodes_setting_is_rejected(tmp_path: Path) -> None:
    values = shared_network_values()
    values.pop("trust_epochs")
    values["trusted_nodes"] = []
    path = tmp_path / "shared.json"
    path.write_text(json.dumps(values), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="trusted_nodes"):
        load_shared_network_config(path)
