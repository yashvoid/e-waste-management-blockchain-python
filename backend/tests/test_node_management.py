from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.node_management import router, session_router
from app.crypto.password_verifier import make_verifier
from app.node.mining_controller import MiningController
from app.node.operator_sessions import OperatorSessions
from app.node.pending_pool import PendingTransactionPool
from app.storage.chain_storage import open_chain_storage
from business_helpers import make_network
from chain_helpers import mine, shared_network_values
from dataclasses import replace
from app.config.shared_network import SharedNetworkConfig, TrustEpoch, TrustedNode


@pytest.fixture
def network(tmp_path: Path):
    return make_network(tmp_path)


OPERATOR_PASSWORD = "operator-test-password"


@pytest.fixture
def node_app(tmp_path: Path, network):
    identities, config = network
    identity = identities["node-a"]
    app = FastAPI()
    app.include_router(router)
    app.include_router(session_router)
    with open_chain_storage(tmp_path / "chain", config) as storage:
        pool = PendingTransactionPool(storage)
        mining = MiningController(storage=storage, config=config, pool=pool)
        app.state.node_settings = SimpleNamespace(
            node_id=identity.node_id,
            listen_host="127.0.0.1",
            listen_port=8000,
            peer_port=8443,
            data_dir=storage.data_dir,
            identity_dir=identity.key_path.parent,
            network_config_path=Path("/tmp/nonexistent"),
            peers=(),
        )
        app.state.node_identity = identity
        app.state.shared_network = config
        app.state.chain_storage = storage
        app.state.transaction_relay = SimpleNamespace(pool=pool)
        app.state.mining_controller = mining
        app.state.chain_synchronizer = None
        app.state.peer_monitor = None
        app.state.operator_sessions = OperatorSessions(make_verifier(OPERATOR_PASSWORD))
        client = TestClient(app, client=("127.0.0.1", 50000))
        sign_in = client.post("/api/node/session", json={"password": OPERATOR_PASSWORD})
        client.headers["Authorization"] = f"Bearer {sign_in.json()['token']}"
        yield SimpleNamespace(
            client=client,
            storage=storage,
            config=config,
            pool=pool,
            mining=mining,
            identity=identity,
        )


def test_node_info_returns_identity(node_app):
    response = node_app.client.get("/api/node/info")
    assert response.status_code == 200
    body = response.json()
    assert body["nodeId"] == node_app.identity.node_id
    assert body["listenHost"] == "127.0.0.1"
    assert body["listenPort"] == 8000
    assert body["peerPort"] == 8443
    assert body["certificateSha256"] == node_app.identity.certificate_sha256
    assert body["networkId"] == "test-network"
    assert body["protocolVersion"] == 1
    assert body["peers"] == []


def test_storage_health_returns_genesis_tip(node_app):
    response = node_app.client.get("/api/node/storage")
    assert response.status_code == 200
    body = response.json()
    assert body["blockCount"] == 1
    assert body["tipHeight"] == 0
    assert "tipHash" in body
    assert "dataDir" in body
    assert body["locked"] is False


def test_pending_count_is_zero_on_empty_pool(node_app):
    response = node_app.client.get("/api/node/pending")
    assert response.status_code == 200
    assert response.json() == {"pendingCount": 0}


def test_sync_status_returns_empty_when_no_synchronizer(node_app):
    response = node_app.client.get("/api/node/sync")
    assert response.status_code == 200
    assert response.json() == {"lastSyncByPeer": {}}


def test_mining_status_is_stopped_initially(node_app):
    response = node_app.client.get("/api/node/mining")
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "stopped"
    assert body["blocksMined"] == 0


def test_start_and_stop_mining(node_app):
    start_response = node_app.client.post("/api/node/mining/start")
    assert start_response.status_code == 200
    assert start_response.json()["started"] is True

    status_response = node_app.client.get("/api/node/mining")
    assert status_response.status_code == 200
    assert status_response.json()["state"] == "running"

    stop_response = node_app.client.post("/api/node/mining/stop")
    assert stop_response.status_code == 200
    assert stop_response.json()["stopped"] is True

    final_status = node_app.client.get("/api/node/mining")
    assert final_status.json()["state"] == "stopped"


def test_start_mining_when_already_running_returns_false(node_app):
    node_app.client.post("/api/node/mining/start")
    response = node_app.client.post("/api/node/mining/start")
    assert response.status_code == 200
    assert response.json()["started"] is False
    node_app.client.post("/api/node/mining/stop")


def test_stop_mining_when_not_running_returns_false(node_app):
    response = node_app.client.post("/api/node/mining/stop")
    assert response.status_code == 200
    assert response.json()["stopped"] is False


def test_backup_export_creates_file(node_app, tmp_path):
    destination = tmp_path / "backup" / "chain-backup.jsonl"
    destination.parent.mkdir(parents=True, exist_ok=True)
    response = node_app.client.post(
        "/api/node/backup/export",
        json={"path": str(destination)},
    )
    assert response.status_code == 200
    assert response.json()["blocksExported"] == 1
    assert destination.exists()


def test_backup_export_refuses_existing_file(node_app, tmp_path):
    destination = tmp_path / "existing.jsonl"
    destination.write_text("placeholder", encoding="utf-8")
    response = node_app.client.post(
        "/api/node/backup/export",
        json={"path": str(destination)},
    )
    assert response.status_code == 422


def test_backup_import_from_exported_file(node_app, tmp_path):
    destination = tmp_path / "backup" / "chain-backup.jsonl"
    destination.parent.mkdir(parents=True, exist_ok=True)
    export_response = node_app.client.post(
        "/api/node/backup/export",
        json={"path": str(destination)},
    )
    assert export_response.status_code == 200

    import_response = node_app.client.post(
        "/api/node/backup/import",
        json={"path": str(destination)},
    )
    assert import_response.status_code == 200
    body = import_response.json()
    assert body["addedBlocks"] == 0
    assert body["canonicalChanged"] is False


def test_backup_import_nonexistent_file_returns_422(node_app):
    response = node_app.client.post(
        "/api/node/backup/import",
        json={"path": "/nonexistent/path/backup.jsonl"},
    )
    assert response.status_code == 422
