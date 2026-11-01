import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config.errors import ConfigurationError
from app.main import create_app
from app.node.identity import KEY_FILE_NAME, load_node_identity
from chain_helpers import shared_network_values
from node_helpers import (
    attestation_public_key_for,
    create_identities,
    free_port,
    network_config,
    provision_peers,
    running_peer,
)


def _write_network_file(path: Path, identities) -> Path:
    values = shared_network_values()
    values["trust_epochs"] = [
        {
            "epoch": 0,
            "activation_height": 0,
            "nodes": [
                {
                    "node_id": identity.node_id,
                    "tls_certificate_sha256": identity.certificate_sha256,
                    "attestation_public_key": attestation_public_key_for(identity),
                    "status": "active",
                }
                for identity in identities.values()
            ],
        }
    ]
    path.write_text(json.dumps(values), encoding="utf-8")
    return path


def _environ(tmp_path: Path, node_id: str, identity_dir: Path, network_path: Path, peers: str = "") -> dict[str, str]:
    return {
        "EWASTE_NODE_ID": node_id,
        "EWASTE_LISTEN_HOST": "127.0.0.1",
        "EWASTE_LISTEN_PORT": "8000",
        "EWASTE_PEER_PORT": str(free_port()),
        "EWASTE_DATA_DIR": str(tmp_path / "node-data"),
        "EWASTE_IDENTITY_DIR": str(identity_dir),
        "EWASTE_NETWORK_CONFIG": str(network_path),
        "EWASTE_PEERS": peers,
    }


def test_startup_requires_an_existing_identity(node_environ: dict[str, str], tmp_path: Path) -> None:
    node_environ["EWASTE_IDENTITY_DIR"] = str(tmp_path / "missing-identity")
    with pytest.raises(ConfigurationError, match="never created automatically"), TestClient(create_app(node_environ)):
        pass


def test_startup_refuses_identity_not_in_shared_configuration(tmp_path: Path) -> None:
    identities = create_identities(tmp_path, ["test-node", "node-b"])
    network_path = _write_network_file(tmp_path / "shared.json", {"node-b": identities["node-b"]})
    environ = _environ(tmp_path, "test-node", identities["test-node"].key_path.parent, network_path)

    with pytest.raises(ConfigurationError, match="not listed"), TestClient(create_app(environ)):
        pass


def test_startup_refuses_attestation_key_not_in_shared_configuration(tmp_path: Path) -> None:
    identities = create_identities(tmp_path, ["test-node"])
    network_path = _write_network_file(tmp_path / "shared.json", identities)
    values = json.loads(network_path.read_text(encoding="utf-8"))
    values["trust_epochs"][0]["nodes"][0]["attestation_public_key"] = "03" + "22" * 32
    network_path.write_text(json.dumps(values), encoding="utf-8")
    environ = _environ(tmp_path, "test-node", identities["test-node"].key_path.parent, network_path)

    with pytest.raises(ConfigurationError, match="attestation key"), TestClient(create_app(environ)):
        pass


def test_restarted_node_keeps_its_identity(tmp_path: Path) -> None:
    identities = create_identities(tmp_path, ["test-node"])
    identity_dir = identities["test-node"].key_path.parent
    network_path = _write_network_file(tmp_path / "shared.json", identities)
    environ = _environ(tmp_path, "test-node", identity_dir, network_path)
    key_before = (identity_dir / KEY_FILE_NAME).read_bytes()

    with TestClient(create_app(environ)) as client:
        assert client.get("/api/health").status_code == 200
    with TestClient(create_app(environ)) as client:
        assert client.get("/api/health").status_code == 200

    assert (identity_dir / KEY_FILE_NAME).read_bytes() == key_before
    assert load_node_identity(identity_dir) == identities["test-node"]


def test_startup_connects_to_a_configured_peer(tmp_path: Path) -> None:
    identities = create_identities(tmp_path, ["test-node", "node-b"])
    config = network_config(identities)
    network_path = _write_network_file(tmp_path / "shared.json", identities)
    provision_peers(identities, config, "test-node", ["node-b"])
    certs_b = provision_peers(identities, config, "node-b", ["test-node"])
    port_b = free_port()
    environ = _environ(
        tmp_path, "test-node", identities["test-node"].key_path.parent, network_path, f"node-b@127.0.0.1:{port_b}"
    )
    with running_peer(identities["node-b"], config, port_b, certs_b, tmp_path / "data-b"):
        with TestClient(create_app(environ)) as client:
            monitor = client.app.state.peer_monitor
            deadline = time.monotonic() + 15
            while monitor.snapshot()[0].state != "connected":
                assert time.monotonic() < deadline, "The configured peer did not connect."
                time.sleep(0.05)
