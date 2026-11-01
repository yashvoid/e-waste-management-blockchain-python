from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.health import router as health_router
from app.api.node_management import require_loopback_client, router, session_router
from app.crypto.password_verifier import make_verifier
from app.node.mining_controller import MiningController
from app.node.operator_sessions import SESSION_IDLE_SECONDS, OperatorSessions
from app.node.pending_pool import PendingTransactionPool
from app.storage.chain_storage import open_chain_storage
from business_helpers import make_network

PASSWORD = "operator-test-password"
OTHER_PASSWORD = "another-operator-password"

MANAGEMENT_ENDPOINTS = [
    ("GET", "/api/node/info", None),
    ("GET", "/api/node/storage", None),
    ("GET", "/api/node/pending", None),
    ("GET", "/api/node/sync", None),
    ("GET", "/api/node/mining", None),
    ("POST", "/api/node/mining/start", None),
    ("POST", "/api/node/mining/stop", None),
    ("POST", "/api/node/backup/export", {"path": "/nonexistent/export/chain.jsonl"}),
    ("POST", "/api/node/backup/import", {"path": "/nonexistent/import/chain.jsonl"}),
]

LOOPBACK_HOSTS = ["127.0.0.1", "::1", "::ffff:127.0.0.1"]
REMOTE_HOSTS = ["203.0.113.7", "10.0.0.5", "2001:db8::1", "fe80::1", "testclient", "not-an-address"]


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def network(tmp_path: Path):
    return make_network(tmp_path)


@pytest.fixture
def storage(tmp_path: Path, network):
    _, config = network
    with open_chain_storage(tmp_path / "chain", config) as chain_storage:
        yield chain_storage


@pytest.fixture
def verifier() -> str:
    return make_verifier(PASSWORD)


def build_app(storage, network, sessions: OperatorSessions) -> FastAPI:
    identities, config = network
    identity = identities["node-a"]
    pool = PendingTransactionPool(storage)
    app = FastAPI()
    app.include_router(health_router)
    app.include_router(session_router)
    app.include_router(router)
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
    app.state.mining_controller = MiningController(storage=storage, config=config, pool=pool)
    app.state.chain_synchronizer = None
    app.state.peer_monitor = None
    app.state.operator_sessions = sessions
    return app


def client_at(app: FastAPI, host: str, port: int = 50000, headers: dict[str, str] | None = None) -> TestClient:
    return TestClient(app, client=(host, port), headers=headers or {})


@pytest.fixture
def app(storage, network, verifier, clock):
    return build_app(storage, network, OperatorSessions(verifier, clock=clock))


def sign_in(client: TestClient, password: str = PASSWORD) -> str:
    response = client.post("/api/node/session", json={"password": password})
    assert response.status_code == 200
    return response.json()["token"]


def authorized(client: TestClient) -> TestClient:
    token = sign_in(client)
    client.headers["Authorization"] = f"Bearer {token}"
    return client


@pytest.mark.parametrize("host", LOOPBACK_HOSTS)
def test_loopback_clients_are_accepted(app, host):
    client = authorized(client_at(app, host))
    assert client.get("/api/node/info").status_code == 200


@pytest.mark.parametrize("host", REMOTE_HOSTS)
def test_remote_clients_are_rejected_even_with_a_valid_session(app, host):
    local = authorized(client_at(app, "127.0.0.1"))
    token = local.headers["Authorization"]
    remote = client_at(app, host, headers={"Authorization": token})
    response = remote.get("/api/node/info")
    assert response.status_code == 403


def test_remote_sign_in_is_rejected(app):
    remote = client_at(app, "203.0.113.7")
    response = remote.post("/api/node/session", json={"password": PASSWORD})
    assert response.status_code == 403


def test_forged_forwarding_headers_do_not_bypass_localhost_restriction(app):
    forged = {
        "X-Forwarded-For": "127.0.0.1",
        "X-Real-IP": "127.0.0.1",
        "Forwarded": "for=127.0.0.1;proto=http",
        "Client-IP": "::1",
    }
    remote = client_at(app, "203.0.113.7", headers=forged)
    assert remote.get("/api/node/info").status_code == 403
    assert remote.post("/api/node/session", json={"password": PASSWORD}).status_code == 403


def test_missing_client_address_is_rejected():
    request = SimpleNamespace(client=None)
    with pytest.raises(HTTPException) as excinfo:
        require_loopback_client(request)
    assert excinfo.value.status_code == 403


@pytest.mark.parametrize("method,path,body", MANAGEMENT_ENDPOINTS)
def test_every_management_endpoint_requires_a_session(app, method, path, body):
    client = client_at(app, "127.0.0.1")
    assert client.request(method, path, json=body).status_code == 401


@pytest.mark.parametrize("method,path,body", MANAGEMENT_ENDPOINTS)
def test_invalid_session_tokens_are_rejected(app, method, path, body):
    client = client_at(app, "127.0.0.1", headers={"Authorization": "Bearer not-a-real-token"})
    assert client.request(method, path, json=body).status_code == 401
    basic = client_at(app, "127.0.0.1", headers={"Authorization": "Basic b3BlcmF0b3I6cHc="})
    assert basic.request(method, path, json=body).status_code == 401


@pytest.mark.parametrize("method,path,body", MANAGEMENT_ENDPOINTS)
def test_remote_clients_cannot_use_management_endpoints_with_a_token(app, method, path, body):
    local = authorized(client_at(app, "127.0.0.1"))
    token = local.headers["Authorization"]
    remote = client_at(app, "203.0.113.7", headers={"Authorization": token})
    assert remote.request(method, path, json=body).status_code == 403


def test_read_only_management_endpoints_return_data_with_a_session(app):
    client = authorized(client_at(app, "127.0.0.1"))
    for path in ["/api/node/info", "/api/node/storage", "/api/node/pending", "/api/node/sync", "/api/node/mining"]:
        assert client.get(path).status_code == 200


def test_public_health_endpoint_remains_accessible_remotely(app):
    remote = client_at(app, "203.0.113.7")
    assert remote.get("/api/health").status_code == 200


def test_correct_password_returns_token_and_idle_timeout(app):
    response = client_at(app, "127.0.0.1").post("/api/node/session", json={"password": PASSWORD})
    assert response.status_code == 200
    body = response.json()
    assert len(body["token"]) >= 40
    assert body["idleTimeoutSeconds"] == SESSION_IDLE_SECONDS


def test_incorrect_password_is_rejected_without_a_token(app):
    response = client_at(app, "127.0.0.1").post("/api/node/session", json={"password": "wrong-password-value"})
    assert response.status_code == 401
    assert "token" not in response.json()


def test_sign_in_without_configured_password_is_unavailable(storage, network):
    app = build_app(storage, network, OperatorSessions(None))
    response = client_at(app, "127.0.0.1").post("/api/node/session", json={"password": PASSWORD})
    assert response.status_code == 503


def test_password_input_is_bounded(app):
    response = client_at(app, "127.0.0.1").post("/api/node/session", json={"password": "x" * 1000})
    assert response.status_code == 422


def test_each_node_uses_its_own_operator_password(storage, network, clock):
    node_b_verifier = make_verifier(OTHER_PASSWORD)
    app_b = build_app(storage, network, OperatorSessions(node_b_verifier, clock=clock))
    client = client_at(app_b, "127.0.0.1")
    assert client.post("/api/node/session", json={"password": PASSWORD}).status_code == 401
    assert client.post("/api/node/session", json={"password": OTHER_PASSWORD}).status_code == 200


def test_logout_invalidates_the_session(app):
    client = authorized(client_at(app, "127.0.0.1"))
    assert client.get("/api/node/info").status_code == 200
    assert client.delete("/api/node/session").status_code == 200
    assert client.get("/api/node/info").status_code == 401


def test_logout_without_a_session_is_rejected(app):
    assert client_at(app, "127.0.0.1").delete("/api/node/session").status_code == 401


def test_session_expires_after_inactivity(app, clock):
    client = authorized(client_at(app, "127.0.0.1"))
    clock.advance(SESSION_IDLE_SECONDS - 60)
    assert client.get("/api/node/info").status_code == 200
    clock.advance(SESSION_IDLE_SECONDS - 60)
    assert client.get("/api/node/info").status_code == 200
    clock.advance(SESSION_IDLE_SECONDS)
    assert client.get("/api/node/info").status_code == 401


def test_sessions_are_cleared_on_restart(storage, network, verifier, clock):
    first = build_app(storage, network, OperatorSessions(verifier, clock=clock))
    old_token = sign_in(client_at(first, "127.0.0.1"))
    restarted = build_app(storage, network, OperatorSessions(verifier, clock=clock))
    client = client_at(restarted, "127.0.0.1", headers={"Authorization": f"Bearer {old_token}"})
    assert client.get("/api/node/info").status_code == 401


def test_repeated_wrong_passwords_lock_further_sign_in(app, clock):
    client = client_at(app, "127.0.0.1")
    for _ in range(5):
        assert client.post("/api/node/session", json={"password": "wrong-password-value"}).status_code == 401
    locked = client.post("/api/node/session", json={"password": PASSWORD})
    assert locked.status_code == 429
    clock.advance(15 * 60)
    assert client.post("/api/node/session", json={"password": PASSWORD}).status_code == 200


def test_successful_sign_in_resets_failed_attempt_count(app):
    client = client_at(app, "127.0.0.1")
    for _ in range(4):
        client.post("/api/node/session", json={"password": "wrong-password-value"})
    assert client.post("/api/node/session", json={"password": PASSWORD}).status_code == 200
    for _ in range(4):
        client.post("/api/node/session", json={"password": "wrong-password-value"})
    assert client.post("/api/node/session", json={"password": PASSWORD}).status_code == 200
