import asyncio
import concurrent.futures
import logging
import ssl
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal, TypeVar

from app.blockchain.structures import Block
from app.blockchain.validation import ValidationError
from app.config.node_settings import PeerAddress
from app.config.shared_network import SharedNetworkConfig
from app.node.peer_chain import canonical_locator, known_block
from app.node.peer_client import (
    PeerRejectedError,
    PeerUnavailableError,
    fetch_blocks_after,
    fetch_common_block,
    fetch_peer_tip,
    incompatibility,
)
from app.node.peer_monitor import PeerTiming
from app.node.peer_protocol import MAX_BLOCKS_PER_REQUEST, RESPONSE_OVERHEAD_BYTES
from app.node.pending_pool import PendingTransactionPool
from app.storage.chain_storage import ChainStorage
from app.storage.errors import StorageError

logger = logging.getLogger(__name__)

T = TypeVar("T")

SyncState = Literal["up_to_date", "synchronized", "incomplete", "unavailable", "rejected", "invalid_data"]


@dataclass(frozen=True)
class SyncOutcome:
    state: SyncState
    detail: str
    blocks_received: int = 0
    removed_transactions: int = 0
    newly_confirmed_transactions: int = 0


class ChainSynchronizer:
    def __init__(
        self,
        *,
        chain_storage: ChainStorage,
        shared_config: SharedNetworkConfig,
        contexts: Mapping[str, ssl.SSLContext],
        timing: PeerTiming,
        pool: PendingTransactionPool,
    ) -> None:
        self._storage = chain_storage
        self._pool = pool
        self._shared_config = shared_config
        self._contexts = contexts
        self._timing = timing
        self._response_limit = (
            MAX_BLOCKS_PER_REQUEST * shared_config.max_block_size_bytes * 2 + RESPONSE_OVERHEAD_BYTES
        )
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="chain-sync")
        self._last_outcomes: dict[str, SyncOutcome] = {}

    def close(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=True)

    def last_outcomes(self) -> dict[str, SyncOutcome]:
        return dict(self._last_outcomes)

    async def _storage_call(self, function: Callable[..., T], *args: object) -> T:
        return await asyncio.wrap_future(self._executor.submit(function, *args))

    async def sync_peer(self, peer: PeerAddress) -> SyncOutcome:
        context = self._contexts[peer.node_id]
        try:
            outcome = await self._sync(peer, context)
        except PeerUnavailableError as exc:
            outcome = SyncOutcome("unavailable", str(exc))
        except PeerRejectedError as exc:
            outcome = SyncOutcome("rejected", str(exc))
        self._last_outcomes[peer.node_id] = outcome
        return outcome

    async def _sync(self, peer: PeerAddress, context: ssl.SSLContext) -> SyncOutcome:
        tip = await fetch_peer_tip(peer, context, self._timing.request_timeout_seconds)
        problem = incompatibility(tip.hello, peer.node_id, self._shared_config)
        if problem is not None:
            return SyncOutcome("rejected", problem)
        if await self._storage_call(known_block, self._storage, tip.tip_hash):
            return SyncOutcome("up_to_date", "Already has the peer's chain tip.")

        locator = await self._storage_call(canonical_locator, self._storage)
        cursor = await fetch_common_block(peer, context, self._timing.request_timeout_seconds, locator)
        if cursor not in locator:
            return SyncOutcome("invalid_data", "The peer does not share a block with this node.")

        received = removed = newly_confirmed = 0
        while cursor != tip.tip_hash:
            blocks = await fetch_blocks_after(
                peer,
                context,
                self._timing.block_request_timeout_seconds,
                cursor,
                MAX_BLOCKS_PER_REQUEST,
                self._response_limit,
            )
            if not blocks:
                break
            if not _links_from(blocks, cursor):
                return SyncOutcome("invalid_data", "The peer sent blocks that do not connect to each other.")
            try:
                updates = await self._storage_call(self._storage.add_blocks, blocks)
            except (ValidationError, StorageError):
                return SyncOutcome(
                    "invalid_data",
                    "The peer sent a block that failed validation.",
                    received,
                    removed,
                    newly_confirmed,
                )
            received += len(blocks)
            removed += sum(len(update.removed_transactions) for update in updates)
            newly_confirmed += sum(len(update.newly_confirmed_transactions) for update in updates)
            removed_transactions = [tx for update in updates for tx in update.removed_transactions]
            await self._storage_call(self._pool.reconcile, removed_transactions)
            cursor = blocks[-1].block_hash
            if len(blocks) < MAX_BLOCKS_PER_REQUEST:
                break

        if cursor == tip.tip_hash:
            return SyncOutcome("synchronized", "Chain synchronized.", received, removed, newly_confirmed)
        return SyncOutcome(
            "incomplete",
            "The peer's chain changed or ended before synchronization finished.",
            received,
            removed,
            newly_confirmed,
        )


def _links_from(blocks: list[Block], cursor: str) -> bool:
    previous = cursor
    for block in blocks:
        if block.previous_hash != previous:
            return False
        previous = block.block_hash
    return True
