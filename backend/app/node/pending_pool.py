import threading
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from app.blockchain.ledger import ChainLedger
from app.blockchain.participants import ParticipantRuleError
from app.blockchain.structures import Transaction, transaction_sort_key
from app.blockchain.validation import ValidationError, validate_transaction
from app.crypto.canonical import canonical_bytes
from app.storage.chain_storage import ChainStorage

MAX_PENDING_TRANSACTIONS = 1000
TRANSACTION_ENVELOPE_ALLOWANCE_BYTES = 2048
BLOCK_OVERHEAD_ALLOWANCE_BYTES = 2048

AdmissionState = Literal["accepted", "known", "confirmed", "rejected", "unavailable"]


@dataclass(frozen=True)
class AdmissionResult:
    state: AdmissionState
    detail: str


class PendingTransactionPool:
    def __init__(self, storage: ChainStorage, capacity: int = MAX_PENDING_TRANSACTIONS) -> None:
        self._storage = storage
        self._capacity = capacity
        self._lock = threading.Lock()
        self._entries: dict[str, Transaction] = {}
        self._confirmed: frozenset[str] = frozenset()
        self._confirmed_tip_hash: str | None = None
        self._ledger_tip_hash: str | None = None
        self._ledger = ChainLedger()
        with self._storage.lock:
            self._refresh_confirmed()

    def _refresh_confirmed(self) -> None:
        tip_hash = self._storage.store.tip.block_hash
        if tip_hash == self._confirmed_tip_hash:
            return
        self._confirmed = frozenset(
            transaction.txid for block in self._storage.store.canonical_chain for transaction in block.transactions
        )
        self._confirmed_tip_hash = tip_hash
        with self._lock:
            for txid in self._confirmed.intersection(self._entries):
                del self._entries[txid]

    def _tip_ledger(self) -> ChainLedger:
        tip_hash = self._storage.store.tip.block_hash
        if tip_hash != self._ledger_tip_hash:
            self._ledger = ChainLedger.from_blocks(self._storage.store.canonical_chain, self._storage.config)
            self._ledger_tip_hash = tip_hash
        return self._ledger

    def admit(self, transaction: Transaction) -> AdmissionResult:
        with self._storage.lock:
            self._refresh_confirmed()
            return self._admit_locked(transaction)

    def _admit_locked(self, transaction: Transaction) -> AdmissionResult:
        with self._lock:
            if transaction.txid in self._entries:
                return AdmissionResult("known", "The transaction is already pending on this node.")
            if transaction.txid in self._confirmed:
                return AdmissionResult("confirmed", "The transaction is already confirmed in the accepted chain.")
            try:
                validate_transaction(transaction, self._storage.config)
            except ValidationError as exc:
                return AdmissionResult("rejected", str(exc))
            try:
                self._tip_ledger().check(
                    transaction,
                    block_timestamp=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    height=self._storage.store.tip.height + 1,
                    config=self._storage.config,
                )
            except ParticipantRuleError as exc:
                return AdmissionResult("rejected", str(exc))
            if len(canonical_bytes(transaction.to_dict())) > (
                self._storage.config.max_transaction_payload_bytes + TRANSACTION_ENVELOPE_ALLOWANCE_BYTES
            ):
                return AdmissionResult("rejected", "The transaction exceeds the maximum allowed size.")
            if len(self._entries) >= self._capacity:
                return AdmissionResult("unavailable", "The pending transaction pool is full. Try again later.")
            self._entries[transaction.txid] = transaction
            return AdmissionResult("accepted", "The transaction was added to the pending pool.")

    def get(self, txid: str) -> Transaction | None:
        with self._lock:
            return self._entries.get(txid)

    def count(self) -> int:
        with self._lock:
            return len(self._entries)

    def ordered(self) -> tuple[Transaction, ...]:
        with self._lock:
            return tuple(sorted(self._entries.values(), key=transaction_sort_key))

    def eligible_for_block(self, block_timestamp: str) -> tuple[Transaction, ...]:
        config = self._storage.config
        size_budget = config.max_block_size_bytes - BLOCK_OVERHEAD_ALLOWANCE_BYTES
        with self._storage.lock:
            height = self._storage.store.tip.height + 1
            ledger = ChainLedger.from_blocks(self._storage.store.canonical_chain, config)
        ledger.begin_block(block_timestamp)
        selected: list[Transaction] = []
        used = 0
        for transaction in self.ordered():
            if len(selected) >= config.max_transactions_per_block:
                break
            size = len(canonical_bytes(transaction.to_dict()))
            if used + size > size_budget:
                break
            try:
                ledger.apply(transaction, block_timestamp=block_timestamp, height=height, config=config)
            except ParticipantRuleError:
                continue
            selected.append(transaction)
            used += size
        return tuple(selected)

    def reconcile(self, removed_transactions: Sequence[Transaction]) -> None:
        with self._storage.lock:
            self._refresh_confirmed()
            for transaction in sorted(removed_transactions, key=transaction_sort_key):
                self._admit_locked(transaction)
