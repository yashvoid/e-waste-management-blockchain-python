from dataclasses import replace
from pathlib import Path

import pytest
from chain_helpers import shared_network_config
from storage_helpers import add_sibling, extend_chain

from app.storage.backup import export_backup, import_backup
from app.storage.chain_storage import open_chain_storage
from app.storage.errors import StorageError
from app.storage.record_files import BLOCKS_FILE_NAME


def _active_bytes(data_dir: Path) -> bytes:
    return (data_dir / BLOCKS_FILE_NAME).read_bytes()


def _node_with_blocks(root: Path, name: str, config, count: int) -> tuple[Path, list]:
    data_dir = root / name
    with open_chain_storage(data_dir, config) as chain:
        blocks = extend_chain(chain, config, count)
    return data_dir, blocks


def test_export_writes_every_stored_block_outside_active_storage(tmp_path: Path) -> None:
    config = shared_network_config()
    source, blocks = _node_with_blocks(tmp_path, "source", config, 2)
    with open_chain_storage(source, config) as chain:
        add_sibling(chain, config, blocks[0], minute=2, second=5)
    backup = tmp_path / "backups" / "chain.jsonl"
    backup.parent.mkdir()

    count = export_backup(source, config, backup)

    assert count == 4
    assert len(backup.read_text(encoding="utf-8").splitlines()) == 4


def test_export_into_active_storage_is_refused(tmp_path: Path) -> None:
    config = shared_network_config()
    source, _ = _node_with_blocks(tmp_path, "source", config, 1)
    with pytest.raises(StorageError, match="outside the node"):
        export_backup(source, config, source / "backup.jsonl")


def test_export_never_overwrites_an_existing_file(tmp_path: Path) -> None:
    config = shared_network_config()
    source, _ = _node_with_blocks(tmp_path, "source", config, 1)
    existing = tmp_path / "chain.jsonl"
    existing.write_text("keep me", encoding="utf-8")

    with pytest.raises(StorageError, match="already exists"):
        export_backup(source, config, existing)
    assert existing.read_text(encoding="utf-8") == "keep me"


def test_import_into_empty_node_adopts_the_backup_chain(tmp_path: Path) -> None:
    config = shared_network_config()
    source, blocks = _node_with_blocks(tmp_path, "source", config, 3)
    backup = tmp_path / "chain.jsonl"
    export_backup(source, config, backup)

    target = tmp_path / "target"
    result = import_backup(target, config, backup)

    assert result.added_blocks == 3
    assert result.canonical_changed is True
    with open_chain_storage(target, config) as chain:
        assert chain.store.tip.block_hash == blocks[-1].block_hash


def test_older_backup_never_replaces_the_newer_active_chain(tmp_path: Path) -> None:
    config = shared_network_config()
    active, active_blocks = _node_with_blocks(tmp_path, "active", config, 3)
    source, _ = _node_with_blocks(tmp_path, "source", config, 2)
    backup = tmp_path / "older.jsonl"
    export_backup(source, config, backup)
    before = _active_bytes(active)

    result = import_backup(active, config, backup)

    assert result.added_blocks == 0
    assert result.canonical_changed is False
    assert _active_bytes(active) == before
    with open_chain_storage(active, config) as chain:
        assert chain.store.tip.block_hash == active_blocks[-1].block_hash


def test_lower_work_fork_is_kept_without_changing_the_tip(tmp_path: Path) -> None:
    config = shared_network_config()
    active, active_blocks = _node_with_blocks(tmp_path, "active", config, 3)
    source, source_blocks = _node_with_blocks(tmp_path, "source", config, 1)
    with open_chain_storage(source, config) as chain:
        sibling = add_sibling(chain, config, source_blocks[0], minute=2, second=5)
    backup = tmp_path / "fork.jsonl"
    export_backup(source, config, backup)

    result = import_backup(active, config, backup)

    assert result.added_blocks == 1
    assert result.canonical_changed is False
    with open_chain_storage(active, config) as chain:
        assert sibling.block_hash in chain.store.blocks_by_hash
        assert chain.store.tip.block_hash == active_blocks[-1].block_hash


def test_longer_valid_backup_is_adopted(tmp_path: Path) -> None:
    config = shared_network_config()
    active, _ = _node_with_blocks(tmp_path, "active", config, 2)
    source, source_blocks = _node_with_blocks(tmp_path, "source", config, 4)
    backup = tmp_path / "longer.jsonl"
    export_backup(source, config, backup)

    result = import_backup(active, config, backup)

    assert result.canonical_changed is True
    with open_chain_storage(active, config) as chain:
        assert chain.store.tip.block_hash == source_blocks[-1].block_hash


def test_malformed_backup_is_rejected_and_storage_is_untouched(tmp_path: Path) -> None:
    config = shared_network_config()
    active, _ = _node_with_blocks(tmp_path, "active", config, 2)
    before = _active_bytes(active)
    backup = tmp_path / "bad.jsonl"
    source, _ = _node_with_blocks(tmp_path, "source", config, 2)
    export_backup(source, config, backup)
    backup.write_text(backup.read_text(encoding="utf-8") + "garbage\n", encoding="utf-8")

    with pytest.raises(StorageError, match="not valid JSON"):
        import_backup(active, config, backup)
    assert _active_bytes(active) == before


def test_tampered_backup_is_rejected_and_storage_is_untouched(tmp_path: Path) -> None:
    config = shared_network_config()
    active, _ = _node_with_blocks(tmp_path, "active", config, 2)
    before = _active_bytes(active)
    source, _ = _node_with_blocks(tmp_path, "source", config, 3)
    backup = tmp_path / "tampered.jsonl"
    export_backup(source, config, backup)
    lines = backup.read_text(encoding="utf-8").splitlines()
    lines[-1] = lines[-1].replace('"nonce":', '"nonce":1', 1)
    backup.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(StorageError):
        import_backup(active, config, backup)
    assert _active_bytes(active) == before


def test_incomplete_backup_is_rejected(tmp_path: Path) -> None:
    config = shared_network_config()
    source, _ = _node_with_blocks(tmp_path, "source", config, 1)
    backup = tmp_path / "incomplete.jsonl"
    export_backup(source, config, backup)
    backup.write_bytes(backup.read_bytes()[:-1])

    with pytest.raises(StorageError, match="incomplete"):
        import_backup(tmp_path / "target", config, backup)
    assert not (tmp_path / "target").exists()


def test_backup_from_another_network_is_rejected(tmp_path: Path) -> None:
    config = shared_network_config()
    source, _ = _node_with_blocks(tmp_path, "source", config, 1)
    backup = tmp_path / "chain.jsonl"
    export_backup(source, config, backup)
    other_network = replace(config, network_id="another-network")

    with pytest.raises(StorageError, match="genesis"):
        import_backup(tmp_path / "target", other_network, backup)


def test_missing_backup_file_is_reported(tmp_path: Path) -> None:
    config = shared_network_config()
    with pytest.raises(StorageError, match="not found"):
        import_backup(tmp_path / "target", config, tmp_path / "missing.jsonl")
