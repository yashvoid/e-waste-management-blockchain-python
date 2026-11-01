import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from app.config.node_settings import PeerAddress
from app.config.shared_network import SharedNetworkConfig
from app.node.identity import NodeIdentity
from app.node.peer_client import (
    PeerRejectedError,
    PeerUnavailableError,
    fetch_peer_hello,
    incompatibility,
)
from app.node.peer_tls import client_ssl_context

logger = logging.getLogger(__name__)

PeerState = Literal["not_checked", "connected", "unreachable", "rejected", "certificate_missing"]


@dataclass(frozen=True)
class PeerStatus:
    node_id: str
    state: PeerState
    detail: str
    last_checked_at: str | None


@dataclass(frozen=True)
class PeerTiming:
    connected_interval_seconds: float = 15.0
    retry_min_seconds: float = 2.0
    retry_max_seconds: float = 60.0
    request_timeout_seconds: float = 5.0
    block_request_timeout_seconds: float = 20.0


class PeerMonitor:
    def __init__(
        self,
        *,
        identity: NodeIdentity,
        shared_config: SharedNetworkConfig,
        peers: Sequence[PeerAddress],
        trusted_certificates: Mapping[str, Path],
        timing: PeerTiming = PeerTiming(),
        on_connected: Callable[[PeerAddress], Awaitable[object]] | None = None,
    ) -> None:
        self._shared_config = shared_config
        self._on_connected = on_connected
        self._peers = tuple(peers)
        self._timing = timing
        self._contexts = {
            peer.node_id: client_ssl_context(identity, trusted_certificates[peer.node_id])
            for peer in self._peers
            if peer.node_id in trusted_certificates
        }
        self._statuses = {
            peer.node_id: PeerStatus(peer.node_id, "not_checked", "Not checked yet.", None) for peer in self._peers
        }

    def snapshot(self) -> tuple[PeerStatus, ...]:
        return tuple(self._statuses[peer.node_id] for peer in self._peers)

    async def run(self) -> None:
        await asyncio.gather(*(self._watch(peer) for peer in self._peers))

    async def _watch(self, peer: PeerAddress) -> None:
        retry_delay = self._timing.retry_min_seconds
        while True:
            status = await self._check(peer)
            self._statuses[peer.node_id] = status
            if status.state == "connected":
                retry_delay = self._timing.retry_min_seconds
                if self._on_connected is not None:
                    await self._run_on_connected(peer)
                await asyncio.sleep(self._timing.connected_interval_seconds)
            else:
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, self._timing.retry_max_seconds)

    async def _run_on_connected(self, peer: PeerAddress) -> None:
        try:
            await self._on_connected(peer)
        except Exception:
            logger.exception("Background chain synchronization with a peer failed unexpectedly.")

    async def _check(self, peer: PeerAddress) -> PeerStatus:
        context = self._contexts.get(peer.node_id)
        if context is None:
            return self._status(peer, "certificate_missing", "No certificate has been imported for this peer.")
        try:
            hello = await fetch_peer_hello(peer, context, self._timing.request_timeout_seconds)
        except PeerUnavailableError as exc:
            return self._status(peer, "unreachable", str(exc))
        except PeerRejectedError as exc:
            return self._status(peer, "rejected", str(exc))

        problem = incompatibility(hello, peer.node_id, self._shared_config)
        if problem is not None:
            return self._status(peer, "rejected", problem)
        return self._status(peer, "connected", "Connected and verified.")

    def _status(self, peer: PeerAddress, state: PeerState, detail: str) -> PeerStatus:
        checked_at = datetime.now(UTC).isoformat(timespec="seconds")
        return PeerStatus(peer.node_id, state, detail, checked_at)
