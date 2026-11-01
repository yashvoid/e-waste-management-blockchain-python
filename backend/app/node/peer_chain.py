from collections.abc import Sequence
from dataclasses import dataclass

from app.blockchain.structures import Block
from app.storage.chain_storage import ChainStorage


@dataclass(frozen=True)
class TipSummary:
    tip_hash: str
    height: int
    cumulative_work: int


def tip_summary(storage: ChainStorage) -> TipSummary:
    with storage.lock:
        tip = storage.store.tip
        return TipSummary(tip.block_hash, tip.height, storage.store.cumulative_work(tip))


def known_block(storage: ChainStorage, block_hash: str) -> bool:
    with storage.lock:
        return block_hash in storage.store.blocks_by_hash


def canonical_locator(storage: ChainStorage) -> list[str]:
    with storage.lock:
        chain = storage.store.canonical_chain
        heights: list[int] = []
        height = chain[-1].height
        step = 1
        while True:
            heights.append(height)
            if height == 0:
                break
            height = max(0, height - step)
            if len(heights) >= 10:
                step *= 2
        return [chain[item].block_hash for item in heights]


def first_canonical_hash(storage: ChainStorage, hashes: Sequence[str]) -> str | None:
    with storage.lock:
        store = storage.store
        for block_hash in hashes:
            block = store.blocks_by_hash.get(block_hash)
            if block is not None and store.is_canonical(block):
                return block_hash
    return None


def canonical_blocks_after(storage: ChainStorage, block_hash: str, limit: int) -> list[Block]:
    with storage.lock:
        store = storage.store
        block = store.blocks_by_hash.get(block_hash)
        if block is None or not store.is_canonical(block):
            return []
        return store.canonical_chain[block.height + 1 : block.height + 1 + limit]
