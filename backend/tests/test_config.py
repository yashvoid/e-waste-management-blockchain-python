import json
from dataclasses import replace
from pathlib import Path

import pytest

from app.config.errors import ConfigurationError
from app.config.node_settings import (
    DATA_DIR_ENV,
    LISTEN_HOST_ENV,
    LISTEN_PORT_ENV,
    NETWORK_CONFIG_ENV,
    NODE_ID_ENV,
    load_node_settings,
)
from app.config.shared_network import SharedNetworkConfig, load_shared_network_config
from app.node.identity import load_node_identity
from chain_helpers import shared_network_values

REQUIRED_NODE_VARIABLES = [NODE_ID_ENV, LISTEN_HOST_ENV, LISTEN_PORT_ENV, DATA_DIR_ENV, NETWORK_CONFIG_ENV]


def write_shared_config(path: Path, values: dict[str, object]) -> Path:
    path.write_text(json.dumps(values), encoding="utf-8")
    return path


def test_node_settings_load_from_environment(node_environ: dict[str, str], tmp_path: Path) -> None:
    settings = load_node_settings(node_environ)

    assert settings.node_id == "test-node"
    assert settings.listen_host == "127.0.0.1"
    assert settings.listen_port == 8000
    assert settings.data_dir == tmp_path / "node-data"
    assert settings.network_config_path == Path(node_environ[NETWORK_CONFIG_ENV])


@pytest.mark.parametrize("variable", REQUIRED_NODE_VARIABLES)
def test_missing_node_setting_is_reported_by_name(node_environ: dict[str, str], variable: str) -> None:
    del node_environ[variable]

    with pytest.raises(ConfigurationError, match=variable):
        load_node_settings(node_environ)


@pytest.mark.parametrize("variable", REQUIRED_NODE_VARIABLES)
def test_blank_node_setting_is_treated_as_missing(node_environ: dict[str, str], variable: str) -> None:
    node_environ[variable] = "   "

    with pytest.raises(ConfigurationError, match=variable):
        load_node_settings(node_environ)


@pytest.mark.parametrize("port", ["not-a-number", "0", "65536"])
def test_invalid_listen_port_is_rejected(node_environ: dict[str, str], port: str) -> None:
    node_environ[LISTEN_PORT_ENV] = port

    with pytest.raises(ConfigurationError, match=LISTEN_PORT_ENV):
        load_node_settings(node_environ)


def test_shared_network_config_loads(shared_config_path: Path, node_identity_dir: Path) -> None:
    config = load_shared_network_config(shared_config_path)
    identity = load_node_identity(node_identity_dir)

    assert replace(config, trust_epochs=()) == SharedNetworkConfig(**{**shared_network_values(), "trust_epochs": ()})
    assert len(config.trust_epochs) == 1
    assert config.trust_epochs[0].nodes[0].node_id == identity.node_id
    assert config.trust_epochs[0].nodes[0].tls_certificate_sha256 == identity.certificate_sha256


def test_missing_shared_network_config_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="was not found"):
        load_shared_network_config(tmp_path / "absent.json")


def test_invalid_json_in_shared_network_config_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "shared.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="not valid JSON"):
        load_shared_network_config(path)


@pytest.mark.parametrize("content", [json.dumps([1, 2]), json.dumps({"network_id": "x"})])
def test_malformed_shared_network_config_is_rejected(tmp_path: Path, content: str) -> None:
    path = tmp_path / "shared.json"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ConfigurationError):
        load_shared_network_config(path)


@pytest.mark.parametrize("protocol_version", ["1", 0, True, 1.5])
def test_invalid_protocol_version_is_rejected(tmp_path: Path, protocol_version: object) -> None:
    path = write_shared_config(
        tmp_path / "shared.json", dict(shared_network_values(), protocol_version=protocol_version)
    )

    with pytest.raises(ConfigurationError, match="protocol_version"):
        load_shared_network_config(path)


def test_node_specific_setting_is_rejected_from_shared_configuration(tmp_path: Path) -> None:
    path = write_shared_config(
        tmp_path / "shared.json",
        dict(shared_network_values(), listen_port=8000, smtp_password="must-not-be-here"),
    )

    with pytest.raises(ConfigurationError) as excinfo:
        load_shared_network_config(path)

    assert "smtp_password" in str(excinfo.value)
    assert "must-not-be-here" not in str(excinfo.value)


@pytest.mark.parametrize("key", ["genesis_timestamp", "genesis_nonce", "genesis_hash", "initial_difficulty"])
def test_missing_stage_three_setting_is_reported(tmp_path: Path, key: str) -> None:
    values = shared_network_values()
    del values[key]
    path = write_shared_config(tmp_path / "shared.json", values)

    with pytest.raises(ConfigurationError, match=key):
        load_shared_network_config(path)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("initial_difficulty", 0),
        ("initial_difficulty", 33),
        ("initial_difficulty", True),
        ("genesis_nonce", -1),
        ("max_transactions_per_block", 0),
        ("max_transactions_per_block", 101),
        ("max_block_size_bytes", 1024 * 1024 + 1),
        ("max_transaction_payload_bytes", 16 * 1024 + 1),
        ("genesis_timestamp", "2026-01-01T00:00:00+00:00"),
        ("genesis_hash", "ABCD"),
        ("genesis_hash", "zz" * 32),
    ],
)
def test_invalid_stage_three_setting_is_rejected(tmp_path: Path, key: str, value: object) -> None:
    path = write_shared_config(tmp_path / "shared.json", dict(shared_network_values(), **{key: value}))

    with pytest.raises(ConfigurationError, match=key):
        load_shared_network_config(path)
