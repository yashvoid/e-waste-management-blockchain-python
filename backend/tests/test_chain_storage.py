import json
from dataclasses import replace
from pathlib import Path

import pytest
from chain_helpers import shared_network_config
from storage_helpers import add_sibling, extend_chain

from app.storage.chain_storage import open_chain_storage
from app.storage.errors import StorageError
from app.storage.record_files import BLOCKS_FILE_NAME, RECOVERY_DIR_NAME, TIP_FILE_NAME


def _records(data_dir: Path) -> list[str]:
    return (data_dir / BLOCKS_FILE_NAME).read_text(encoding="utf-8").splitlines()


def test_new_storage_starts_with_genesis_and_tip_metadata(tmp_path: Path) -> None:
    config = shared_network_config()
    data_dir = tmp_path / "node"
    with open_chain_storage(data_dir, config) as chain:
        genesis = chain.store.tip
    assert len(_records(data_dir)) == 1
    metadata = json.loads((data_dir / TIP_FILE_NAME).read_text(encoding="utf-8"))
    assert metadata == {"tip_hash": genesis.block_hash, "height": 0}


def test_blocks_survive_restart(tmp_path: Path) -> None:
    config = shared_network_config()
    data_dir = tmp_path / "node"
    with open_chain_storage(data_dir, config) as chain:
        genesis_hash = chain.store.tip.block_hash
        blocks = extend_chain(chain, config, 3)
    with open_chain_storage(data_dir, config) as reopened:
        assert reopened.store.tip.block_hash == blocks[-1].block_hash
        assert reopened.store.tip.height == 3
        assert [block.block_hash for block in reopened.store.canonical_chain] == [
            genesis_hash,
            *(block.block_hash for block in blocks),
        ]


def test_competing_branch_is_kept_in_append_only_records(tmp_path: Path) -> None:
    config = shared_network_config()
    data_dir = tmp_path / "node"
    with open_chain_storage(data_dir, config) as chain:
        first = extend_chain(chain, config, 1)[0]
        sibling = add_sibling(chain, config, chain.store.canonical_chain[0], minute=1, second=5)
    assert len(_records(data_dir)) == 3
    expected_tip = min(first.block_hash, sibling.block_hash)
    with open_chain_storage(data_dir, config) as reopened:
        assert first.block_hash in reopened.store.blocks_by_hash
        assert sibling.block_hash in reopened.store.blocks_by_hash
        assert reopened.store.tip.block_hash == expected_tip


def test_incomplete_final_record_is_recovered_and_preserved(tmp_path: Path) -> None:
    config = shared_network_config()
    data_dir = tmp_path / "node"
    with open_chain_storage(data_dir, config) as chain:
        blocks = extend_chain(chain, config, 2)
    original = (data_dir / BLOCKS_FILE_NAME).read_bytes()
    partial = b'{"height":3,"hash":"abc'
    (data_dir / BLOCKS_FILE_NAME).write_bytes(original + partial)

    with open_chain_storage(data_dir, config) as recovered:
        assert recovered.store.tip.block_hash == blocks[-1].block_hash
    assert (data_dir / BLOCKS_FILE_NAME).read_bytes() == original
    recovery = data_dir / RECOVERY_DIR_NAME
    assert (recovery / "incomplete-tail-1.bin").read_bytes() == partial
    assert (recovery / "blocks-before-recovery-1.jsonl").read_bytes() == original + partial


def test_complete_malformed_record_is_rejected_and_file_is_unchanged(tmp_path: Path) -> None:
    config = shared_network_config()
    data_dir = tmp_path / "node"
    with open_chain_storage(data_dir, config) as chain:
        extend_chain(chain, config, 1)
    corrupted = (data_dir / BLOCKS_FILE_NAME).read_bytes() + b"this is not a block\n"
    (data_dir / BLOCKS_FILE_NAME).write_bytes(corrupted)

    with pytest.raises(StorageError, match="not valid JSON"):
        with open_chain_storage(data_dir, config):
            pass
    assert (data_dir / BLOCKS_FILE_NAME).read_bytes() == corrupted
    assert not (data_dir / RECOVERY_DIR_NAME).exists()


def test_complete_block_failing_validation_is_rejected(tmp_path: Path) -> None:
    config = shared_network_config()
    data_dir = tmp_path / "node"
    with open_chain_storage(data_dir, config) as chain:
        block = extend_chain(chain, config, 1)[0]
    record = json.loads(_records(data_dir)[-1])
    assert record["hash"] == block.block_hash
    record["nonce"] += 1
    tampered = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
    original = (data_dir / BLOCKS_FILE_NAME).read_text(encoding="utf-8")
    (data_dir / BLOCKS_FILE_NAME).write_text(original + tampered, encoding="utf-8")

    with pytest.raises(StorageError, match="failed block validation"):
        with open_chain_storage(data_dir, config):
            pass
    assert (data_dir / BLOCKS_FILE_NAME).read_text(encoding="utf-8") == original + tampered


def test_record_with_unknown_field_is_rejected(tmp_path: Path) -> None:
    config = shared_network_config()
    data_dir = tmp_path / "node"
    with open_chain_storage(data_dir, config):
        pass
    record = json.loads(_records(data_dir)[0])
    record["extra"] = "value"
    (data_dir / BLOCKS_FILE_NAME).write_text(json.dumps(record) + "\n", encoding="utf-8")

    with pytest.raises(StorageError, match="required block structure"):
        with open_chain_storage(data_dir, config):
            pass


def test_untrusted_tip_metadata_is_rebuilt_from_validated_blocks(tmp_path: Path) -> None:
    config = shared_network_config()
    data_dir = tmp_path / "node"
    with open_chain_storage(data_dir, config) as chain:
        blocks = extend_chain(chain, config, 2)
    (data_dir / TIP_FILE_NAME).write_text('{"tip_hash": "ff", "height": 99}', encoding="utf-8")

    with open_chain_storage(data_dir, config) as rebuilt:
        assert rebuilt.store.tip.block_hash == blocks[-1].block_hash
    metadata = json.loads((data_dir / TIP_FILE_NAME).read_text(encoding="utf-8"))
    assert metadata == {"tip_hash": blocks[-1].block_hash, "height": 2}


def test_missing_tip_metadata_is_recreated(tmp_path: Path) -> None:
    config = shared_network_config()
    data_dir = tmp_path / "node"
    with open_chain_storage(data_dir, config) as chain:
        blocks = extend_chain(chain, config, 1)
    (data_dir / TIP_FILE_NAME).unlink()

    with open_chain_storage(data_dir, config):
        pass
    metadata = json.loads((data_dir / TIP_FILE_NAME).read_text(encoding="utf-8"))
    assert metadata["tip_hash"] == blocks[-1].block_hash


def test_second_writer_is_refused_while_storage_is_open(tmp_path: Path) -> None:
    config = shared_network_config()
    data_dir = tmp_path / "node"
    with open_chain_storage(data_dir, config):
        with pytest.raises(StorageError, match="already using"):
            with open_chain_storage(data_dir, config):
                pass


def test_storage_written_for_another_network_is_rejected(tmp_path: Path) -> None:
    config = shared_network_config()
    data_dir = tmp_path / "node"
    with open_chain_storage(data_dir, config):
        pass
    other_network = replace(config, network_id="another-network")

    with pytest.raises(StorageError, match="genesis"):
        with open_chain_storage(data_dir, other_network):
            pass
