import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from app.blockchain.mining import ChainUpdate, add_block, open_chain
from app.blockchain.structures import Block, BlockStore
from app.blockchain.validation import ValidationError, validate_block
from app.config.shared_network import SharedNetworkConfig
from app.storage.block_records import decode_block_record, encode_block_record
from app.storage.data_lock import exclusive_data_lock
from app.storage.errors import StorageError
from app.storage.record_files import (
    append_record,
    read_complete_records,
    read_tip_metadata,
    write_tip_metadata,
)


@dataclass
class ChainStorage:
    data_dir: Path
    config: SharedNetworkConfig
    store: BlockStore
    lock: threading.RLock = field(default_factory=threading.RLock)

    def add_block(self, block: Block) -> ChainUpdate:
        with self.lock:
            if block.block_hash in self.store.blocks_by_hash:
                return add_block(self.store, self.config, block)
            parent = self.store.blocks_by_hash.get(block.previous_hash)
            if parent is None:
                raise ValidationError("The block's parent is not a validated block known to this node.")
            validate_block(block, self.config, self.store.ancestry(parent))
            append_record(self.data_dir, encode_block_record(block))
            update = add_block(self.store, self.config, block)
            if update.canonical_changed:
                _write_tip(self.data_dir, self.store)
            return update

    def add_blocks(self, blocks: Sequence[Block]) -> list[ChainUpdate]:
        with self.lock:
            return [self.add_block(block) for block in blocks]


@contextmanager
def open_chain_storage(data_dir: Path, config: SharedNetworkConfig) -> Iterator[ChainStorage]:
    with exclusive_data_lock(data_dir):
        yield _load(data_dir, config)


def apply_stored_block(store: BlockStore, config: SharedNetworkConfig, block: Block, number: int) -> None:
    if block.height == 0:
        if block != store.canonical_chain[0]:
            raise StorageError(f"Record {number} does not match the genesis block of this network.")
        return
    try:
        add_block(store, config, block)
    except ValidationError as exc:
        raise StorageError(f"Record {number} failed block validation: {exc}") from exc


def open_network_store(config: SharedNetworkConfig) -> BlockStore:
    try:
        return open_chain(config)
    except ValidationError as exc:
        raise StorageError(f"The genesis block does not match this network configuration: {exc}") from exc


def _load(data_dir: Path, config: SharedNetworkConfig) -> ChainStorage:
    store = open_network_store(config)

    lines = read_complete_records(data_dir)
    if not lines:
        append_record(data_dir, encode_block_record(store.canonical_chain[0]))
        lines = read_complete_records(data_dir)
    for number, line in enumerate(lines, start=1):
        apply_stored_block(store, config, decode_block_record(line), number)
    if read_tip_metadata(data_dir) != _tip_summary(store):
        _write_tip(data_dir, store)
    return ChainStorage(data_dir=data_dir, config=config, store=store)


def _tip_summary(store: BlockStore) -> dict[str, object]:
    return {"tip_hash": store.tip.block_hash, "height": store.tip.height}


def _write_tip(data_dir: Path, store: BlockStore) -> None:
    write_tip_metadata(data_dir, store.tip.block_hash, store.tip.height)
