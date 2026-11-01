import threading
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.blockchain.structures import (
    Block,
    BlockStore,
    Transaction,
    block_hash_hex,
    block_header_body,
    compute_transaction_root,
    make_block,
    transaction_sort_key,
)
from app.blockchain.validation import ValidationError, validate_block, verify_genesis
from app.config.shared_network import SharedNetworkConfig
from app.crypto.canonical import MAX_SAFE_INTEGER


@dataclass(frozen=True)
class ChainUpdate:
    canonical_changed: bool
    removed_transactions: tuple[Transaction, ...] = ()
    newly_confirmed_transactions: tuple[Transaction, ...] = ()


def open_chain(config: SharedNetworkConfig) -> BlockStore:
    return BlockStore(verify_genesis(config))


def mine_block(
    config: SharedNetworkConfig,
    parent: Block,
    transactions: Sequence[Transaction],
    timestamp: str,
    cancel: threading.Event,
) -> Block | None:
    ordered = tuple(sorted(transactions, key=transaction_sort_key))
    transaction_root = compute_transaction_root([(transaction.txid, transaction.signature) for transaction in ordered])
    header = block_header_body(
        config.network_id,
        config.protocol_version,
        parent.height + 1,
        parent.block_hash,
        timestamp,
        config.initial_difficulty,
        0,
        transaction_root,
    )
    target = 1 << (256 - config.initial_difficulty)

    nonce = 0
    while not cancel.is_set():
        if nonce > MAX_SAFE_INTEGER:
            raise RuntimeError("No valid block hash was found within the nonce range.")
        header["nonce"] = nonce
        if int(block_hash_hex(header), 16) < target:
            return make_block(
                config.network_id,
                config.protocol_version,
                parent.height + 1,
                parent.block_hash,
                timestamp,
                config.initial_difficulty,
                nonce,
                ordered,
            )
        nonce += 1
    return None


def add_block(store: BlockStore, config: SharedNetworkConfig, block: Block) -> ChainUpdate:
    known = store.blocks_by_hash.get(block.block_hash)
    if known is not None:
        if known != block:
            raise ValidationError("A block with the same hash but different contents was received.")
        return ChainUpdate(canonical_changed=False)
    parent = store.blocks_by_hash.get(block.previous_hash)
    if parent is None:
        raise ValidationError("The block's parent is not a validated block known to this node.")

    validate_block(block, config, store.ancestry(parent))
    store.blocks_by_hash[block.block_hash] = block

    if not _is_preferred(store, block):
        return ChainUpdate(canonical_changed=False)
    return _adopt_branch(store, block)


def _is_preferred(store: BlockStore, candidate: Block) -> bool:
    candidate_work = store.cumulative_work(candidate)
    current_work = store.cumulative_work(store.tip)
    if candidate_work != current_work:
        return candidate_work > current_work
    return candidate.block_hash < store.tip.block_hash


def _adopt_branch(store: BlockStore, new_tip: Block) -> ChainUpdate:
    new_suffix: list[Block] = []
    cursor = new_tip
    while not store.is_canonical(cursor):
        new_suffix.append(cursor)
        cursor = store.blocks_by_hash[cursor.previous_hash]
    new_suffix.reverse()

    old_suffix = store.canonical_chain[cursor.height + 1 :]
    old_txids = _transaction_ids(store.canonical_chain)
    new_txids = _transaction_ids(store.ancestry(new_tip))
    store.canonical_chain = store.canonical_chain[: cursor.height + 1] + new_suffix
    return ChainUpdate(
        canonical_changed=True,
        removed_transactions=_sorted_transactions(old_suffix, excluded_txids=new_txids),
        newly_confirmed_transactions=_sorted_transactions(new_suffix, excluded_txids=old_txids),
    )


def _transaction_ids(blocks: Iterable[Block]) -> set[str]:
    return {transaction.txid for block in blocks for transaction in block.transactions}


def _sorted_transactions(blocks: Iterable[Block], excluded_txids: set[str]) -> tuple[Transaction, ...]:
    transactions = [
        transaction
        for block in blocks
        for transaction in block.transactions
        if transaction.txid not in excluded_txids
    ]
    return tuple(sorted(transactions, key=transaction_sort_key))
