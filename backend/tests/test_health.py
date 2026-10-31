import pytest
from fastapi.testclient import TestClient

from app.config.errors import ConfigurationError
from app.main import create_app


def test_app_starts_with_valid_configuration(node_environ: dict[str, str]) -> None:
    app = create_app(node_environ)

    assert app.state.shared_network.network_id == "test-network"
    assert app.state.node_settings.node_id == "test-node"


def test_health_endpoint_reports_ok(node_environ: dict[str, str]) -> None:
    client = TestClient(create_app(node_environ))

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_unknown_route_returns_not_found(node_environ: dict[str, str]) -> None:
    client = TestClient(create_app(node_environ))

    assert client.get("/api/unknown").status_code == 404


def test_unhandled_error_returns_generic_message(node_environ: dict[str, str]) -> None:
    app = create_app(node_environ)

    @app.get("/api/boom")
    def boom() -> None:
        raise RuntimeError("internal detail that must not leak")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/boom")

    assert response.status_code == 500
    assert response.json() == {"detail": "An unexpected error occurred on the node."}
    assert "internal detail" not in response.text


def test_startup_fails_when_configuration_is_missing(node_environ: dict[str, str]) -> None:
    del node_environ["EWASTE_NODE_ID"]

    with pytest.raises(ConfigurationError, match="EWASTE_NODE_ID"):
        create_app(node_environ)
