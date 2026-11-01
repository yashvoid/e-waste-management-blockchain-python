import logging
import threading
from datetime import UTC, datetime
from typing import Literal

from app.blockchain.mining import add_block, mine_block
from app.blockchain.structures import Block
from app.blockchain.validation import ValidationError
from app.config.shared_network import SharedNetworkConfig
from app.node.pending_pool import PendingTransactionPool
from app.storage.chain_storage import ChainStorage

logger = logging.getLogger(__name__)

MiningState = Literal["stopped", "running", "error"]


class MiningController:
    """Background mining loop that produces blocks from the pending pool.

    Runs on a dedicated thread so the event loop is not blocked.  Each cycle
    selects eligible transactions, mines a block, adds it to storage and
    reconciles the pending pool.  The controller is cancellable at any point
    between cycles; the mine_block call itself receives a cancel event so it
    can abort the nonce search promptly.
    """

    def __init__(
        self,
        *,
        storage: ChainStorage,
        config: SharedNetworkConfig,
        pool: PendingTransactionPool,
    ) -> None:
        self._storage = storage
        self._config = config
        self._pool = pool
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._state_lock = threading.Lock()
        self._state: MiningState = "stopped"
        self._last_error: str = ""
        self._blocks_mined: int = 0
        self._last_block_hash: str = ""
        self._last_block_height: int | None = None

    @property
    def state(self) -> MiningState:
        with self._state_lock:
            return self._state

    @property
    def last_error(self) -> str:
        with self._state_lock:
            return self._last_error

    @property
    def blocks_mined(self) -> int:
        with self._state_lock:
            return self._blocks_mined

    @property
    def last_block_hash(self) -> str:
        with self._state_lock:
            return self._last_block_hash

    @property
    def last_block_height(self) -> int | None:
        with self._state_lock:
            return self._last_block_height

    def start(self) -> bool:
        with self._state_lock:
            if self._state == "running":
                return False
            self._cancel.clear()
            self._state = "running"
            self._last_error = ""
        self._thread = threading.Thread(target=self._run, name="mining", daemon=True)
        self._thread.start()
        logger.info("Mining started.")
        return True

    def stop(self) -> bool:
        with self._state_lock:
            if self._state != "running":
                return False
            self._state = "stopped"
        self._cancel.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=10)
            self._thread = None
        logger.info("Mining stopped.")
        return True

    def status(self) -> dict[str, object]:
        with self._state_lock:
            return {
                "state": self._state,
                "lastError": self._last_error,
                "blocksMined": self._blocks_mined,
                "lastBlockHash": self._last_block_hash,
                "lastBlockHeight": self._last_block_height,
            }

    def _run(self) -> None:
        while not self._cancel.is_set():
            try:
                self._mine_cycle()
            except Exception as exc:
                with self._state_lock:
                    self._state = "error"
                    self._last_error = str(exc)
                logger.exception("Mining cycle failed.")
                return

    def _mine_cycle(self) -> None:
        timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._storage.lock:
            parent: Block = self._storage.store.tip
            transactions = self._pool.eligible_for_block(timestamp)
        if not transactions:
            self._cancel.wait(timeout=2.0)
            return
        block = mine_block(self._config, parent, transactions, timestamp, self._cancel)
        if block is None:
            return
        with self._storage.lock:
            update = add_block(self._storage.store, self._config, block)
            if update.canonical_changed:
                self._pool.reconcile(update.removed_transactions)
        with self._state_lock:
            self._blocks_mined += 1
            self._last_block_hash = block.block_hash
            self._last_block_height = block.height
        logger.info("Mined block %d: %s", block.height, block.block_hash[:12])
