import json
import logging
import ssl
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor

import httpx

from app.blockchain.structures import Transaction
from app.config.node_settings import PeerAddress
from app.node.pending_pool import AdmissionResult, PendingTransactionPool

logger = logging.getLogger(__name__)

RELAY_WORKERS = 4
RELAY_ATTEMPTS = 2
RELAY_RETRY_DELAY_SECONDS = 0.5


class TransactionRelay:
    def __init__(
        self,
        *,
        node_id: str,
        pool: PendingTransactionPool,
        peers: Sequence[PeerAddress],
        contexts: Mapping[str, ssl.SSLContext],
        timeout_seconds: float,
    ) -> None:
        self._node_id = node_id
        self._pool = pool
        self._peers = tuple(peers)
        self._contexts = contexts
        self._timeout_seconds = timeout_seconds
        self._executor = ThreadPoolExecutor(max_workers=RELAY_WORKERS, thread_name_prefix="tx-relay")

    def close(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=True)

    def submit_local(self, transaction: Transaction) -> AdmissionResult:
        result = self._pool.admit(transaction)
        if result.state == "accepted":
            self._announce(transaction, exclude_node_id=None)
        return result

    def receive(self, transaction: Transaction, origin_node_id: str | None) -> AdmissionResult:
        result = self._pool.admit(transaction)
        if result.state == "accepted":
            self._announce(transaction, exclude_node_id=origin_node_id)
        return result

    def send_pending_to(self, peer: PeerAddress) -> None:
        for transaction in self._pool.ordered():
            self._executor.submit(self._send, peer, transaction)

    def _announce(self, transaction: Transaction, exclude_node_id: str | None) -> None:
        for peer in self._peers:
            if peer.node_id != exclude_node_id:
                self._executor.submit(self._send, peer, transaction)

    def _send(self, peer: PeerAddress, transaction: Transaction) -> None:
        body = json.dumps(
            {"transaction": transaction.to_dict(), "originNodeId": self._node_id},
            separators=(",", ":"),
        ).encode("utf-8")
        url = f"https://{peer.host}:{peer.port}/peer/transactions"
        for attempt in range(RELAY_ATTEMPTS):
            try:
                with httpx.Client(verify=self._contexts[peer.node_id], timeout=self._timeout_seconds) as client:
                    response = client.post(url, content=body, headers={"Content-Type": "application/json"})
                if response.status_code == 200:
                    return
                logger.warning("Peer %s did not accept a transaction announcement.", peer.node_id)
                return
            except httpx.HTTPError:
                if attempt + 1 < RELAY_ATTEMPTS:
                    time.sleep(RELAY_RETRY_DELAY_SECONDS)
        logger.info("Peer %s is unreachable; pending transactions will be re-sent when it reconnects.", peer.node_id)
