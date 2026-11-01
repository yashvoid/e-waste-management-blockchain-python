import json
from pathlib import Path

import pytest

from app.node.attestation import attestation_public_key_hex, load_attestation_key
from app.node.identity import create_node_identity, load_node_identity
from chain_helpers import shared_network_values


@pytest.fixture
def node_identity_dir(tmp_path: Path) -> Path:
    identity_dir = tmp_path / "identity"
    create_node_identity(identity_dir, "test-node")
    return identity_dir


@pytest.fixture
def shared_config_path(tmp_path: Path, node_identity_dir: Path) -> Path:
    identity = load_node_identity(node_identity_dir)
    values = shared_network_values()
    values["trust_epochs"] = [
        {
            "epoch": 0,
            "activation_height": 0,
            "nodes": [
                {
                    "node_id": identity.node_id,
                    "tls_certificate_sha256": identity.certificate_sha256,
                    "attestation_public_key": attestation_public_key_hex(load_attestation_key(node_identity_dir)),
                    "status": "active",
                }
            ],
        }
    ]
    path = tmp_path / "shared-network.json"
    path.write_text(json.dumps(values), encoding="utf-8")
    return path


@pytest.fixture
def node_environ(tmp_path: Path, shared_config_path: Path, node_identity_dir: Path) -> dict[str, str]:
    return {
        "EWASTE_NODE_ID": "test-node",
        "EWASTE_LISTEN_HOST": "127.0.0.1",
        "EWASTE_LISTEN_PORT": "8000",
        "EWASTE_PEER_PORT": "8443",
        "EWASTE_DATA_DIR": str(tmp_path / "node-data"),
        "EWASTE_IDENTITY_DIR": str(node_identity_dir),
        "EWASTE_NETWORK_CONFIG": str(shared_config_path),
    }
