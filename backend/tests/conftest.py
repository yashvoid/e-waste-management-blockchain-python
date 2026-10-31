import json
from pathlib import Path

import pytest


@pytest.fixture
def shared_config_path(tmp_path: Path) -> Path:
    path = tmp_path / "shared-network.json"
    path.write_text(
        json.dumps({"network_id": "test-network", "protocol_version": 1}),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def node_environ(tmp_path: Path, shared_config_path: Path) -> dict[str, str]:
    return {
        "EWASTE_NODE_ID": "test-node",
        "EWASTE_LISTEN_HOST": "127.0.0.1",
        "EWASTE_LISTEN_PORT": "8000",
        "EWASTE_DATA_DIR": str(tmp_path / "node-data"),
        "EWASTE_NETWORK_CONFIG": str(shared_config_path),
    }
