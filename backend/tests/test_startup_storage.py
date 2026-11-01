import json
from pathlib import Path

import pytest
from chain_helpers import shared_network_values
from fastapi.testclient import TestClient
from storage_helpers import extend_chain

from app.config.shared_network import load_shared_network_config
from app.main import create_app
from app.storage.chain_storage import open_chain_storage
from app.storage.errors import StorageError
from app.storage.record_files import BLOCKS_FILE_NAME, TIP_FILE_NAME


def _data_dir(node_environ: dict[str, str]) -> Path:
    return Path(node_environ["EWASTE_DATA_DIR"])


def _shared_config(node_environ: dict[str, str]):
    return load_shared_network_config(Path(node_environ["EWASTE_NETWORK_CONFIG"]))


def test_startup_with_empty_data_directory_creates_genesis_storage(node_environ: dict[str, str]) -> None:
    app = create_app(node_environ)

    with TestClient(app) as client:
        chain_storage = client.app.state.chain_storage
        assert chain_storage.store.tip.height == 0
        assert chain_storage.store.tip.block_hash == chain_storage.store.canonical_chain[0].block_hash

    assert len((_data_dir(node_environ) / BLOCKS_FILE_NAME).read_text(encoding="utf-8").splitlines()) == 1
    assert (_data_dir(node_environ) / TIP_FILE_NAME).is_file()


def test_startup_with_existing_valid_chain_restores_canonical_tip(node_environ: dict[str, str]) -> None:
    config = _shared_config(node_environ)
    with open_chain_storage(_data_dir(node_environ), config) as chain:
        blocks = extend_chain(chain, config, 3)

    with TestClient(create_app(node_environ)) as client:
        store = client.app.state.chain_storage.store
        assert store.tip.block_hash == blocks[-1].block_hash
        assert store.tip.height == 3


def test_startup_fails_clearly_when_stored_data_is_invalid(node_environ: dict[str, str]) -> None:
    config = _shared_config(node_environ)
    with open_chain_storage(_data_dir(node_environ), config) as chain:
        extend_chain(chain, config, 1)
    with (_data_dir(node_environ) / BLOCKS_FILE_NAME).open("a", encoding="utf-8") as handle:
        handle.write("not a block\n")

    with pytest.raises(StorageError, match="not valid JSON"):
        with TestClient(create_app(node_environ)):
            pass


def test_startup_fails_when_genesis_does_not_match_network(node_environ: dict[str, str], tmp_path: Path) -> None:
    config = _shared_config(node_environ)
    with open_chain_storage(_data_dir(node_environ), config):
        pass
    other_values = json.loads(Path(node_environ["EWASTE_NETWORK_CONFIG"]).read_text(encoding="utf-8"))
    other_values["network_id"] = "another-network"
    other_config = tmp_path / "other-network.json"
    other_config.write_text(json.dumps(other_values), encoding="utf-8")
    other_environ = {**node_environ, "EWASTE_NETWORK_CONFIG": str(other_config)}

    with pytest.raises(StorageError, match="genesis"):
        with TestClient(create_app(other_environ)):
            pass


def test_startup_fails_when_another_writer_holds_the_lock(node_environ: dict[str, str]) -> None:
    config = _shared_config(node_environ)

    with open_chain_storage(_data_dir(node_environ), config):
        with pytest.raises(StorageError, match="already using"):
            with TestClient(create_app(node_environ)):
                pass


def test_shutdown_releases_the_writer_lock(node_environ: dict[str, str]) -> None:
    config = _shared_config(node_environ)
    with TestClient(create_app(node_environ)):
        pass

    with open_chain_storage(_data_dir(node_environ), config) as chain:
        assert chain.store.tip.height == 0


def test_health_endpoint_still_works_with_storage_lifecycle(node_environ: dict[str, str]) -> None:
    with TestClient(create_app(node_environ)) as client:
        assert client.get("/api/health").json() == {"status": "ok"}
