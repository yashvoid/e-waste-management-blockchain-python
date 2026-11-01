import os
from dataclasses import dataclass
from pathlib import Path

from app.blockchain.structures import BlockStore
from app.config.shared_network import SharedNetworkConfig
from app.storage.block_records import decode_block_record, encode_block_record
from app.storage.chain_storage import ChainStorage, apply_stored_block, open_chain_storage, open_network_store
from app.storage.errors import StorageError
from app.storage.record_files import split_record_text



@dataclass(frozen=True)
class ImportResult:
    added_blocks: int
    canonical_changed: bool


def export_backup(data_dir: Path, config: SharedNetworkConfig, destination: Path) -> int:
    if not destination.parent.is_dir():
        raise StorageError("The folder for the backup file does not exist.")
    if destination.resolve().is_relative_to(data_dir.resolve()):
        raise StorageError("Backups must be saved outside the node's active blockchain storage.")
    if destination.exists():
        raise StorageError("A file already exists at the backup location. Choose a new file name.")
    with open_chain_storage(data_dir, config) as chain:
        lines = [encode_block_record(block) for block in chain.store.blocks_by_hash.values()]
    _write_atomically(destination, "".join(lines))
    return len(lines)


def export_backup_from_store(storage: ChainStorage, destination: Path) -> int:
    if not destination.parent.is_dir():
        raise StorageError("The folder for the backup file does not exist.")
    if destination.resolve().is_relative_to(storage.data_dir.resolve()):
        raise StorageError("Backups must be saved outside the node's active blockchain storage.")
    if destination.exists():
        raise StorageError("A file already exists at the backup location. Choose a new file name.")
    with storage.lock:
        lines = [encode_block_record(block) for block in storage.store.blocks_by_hash.values()]
    _write_atomically(destination, "".join(lines))
    return len(lines)


def import_backup(data_dir: Path, config: SharedNetworkConfig, source: Path) -> ImportResult:
    if not source.is_file():
        raise StorageError("The selected backup file was not found.")
    candidate = _validated_candidate(config, _read_backup_lines(source))
    with open_chain_storage(data_dir, config) as chain:
        tip_before = chain.store.tip.block_hash
        added = 0
        for block in list(candidate.blocks_by_hash.values()):
            if block.block_hash in chain.store.blocks_by_hash:
                continue
            chain.add_block(block)
            added += 1
        return ImportResult(added_blocks=added, canonical_changed=chain.store.tip.block_hash != tip_before)


def import_backup_to_store(storage: ChainStorage, source: Path) -> ImportResult:
    if not source.is_file():
        raise StorageError("The selected backup file was not found.")
    candidate = _validated_candidate(storage.config, _read_backup_lines(source))
    with storage.lock:
        tip_before = storage.store.tip.block_hash
        added = 0
        for block in list(candidate.blocks_by_hash.values()):
            if block.block_hash in storage.store.blocks_by_hash:
                continue
            storage.add_block(block)
            added += 1
        return ImportResult(added_blocks=added, canonical_changed=storage.store.tip.block_hash != tip_before)


def _read_backup_lines(source: Path) -> list[str]:
    try:
        text = source.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise StorageError("The selected backup file could not be read as text.") from exc
    try:
        lines = split_record_text(text)
    except StorageError as exc:
        raise StorageError("The backup file is incomplete and cannot be imported.") from exc
    if not lines:
        raise StorageError("The backup file contains no blocks.")
    return lines


def _validated_candidate(config: SharedNetworkConfig, lines: list[str]) -> BlockStore:
    store = open_network_store(config)
    for number, line in enumerate(lines, start=1):
        apply_stored_block(store, config, decode_block_record(line), number)
    return store


def _write_atomically(destination: Path, text: str) -> None:
    temporary = destination.with_name(destination.name + ".tmp")
    with open(temporary, "wb") as handle:
        handle.write(text.encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, destination)
