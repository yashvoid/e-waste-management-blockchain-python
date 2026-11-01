import asyncio
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path

import pytest

from app.config.node_settings import PeerAddress
from app.node.identity import NodeIdentity, create_node_identity
from app.node.peer_client import PeerRejectedError, fetch_peer_hello
from app.node.peer_monitor import PeerMonitor, PeerStatus, PeerTiming
from app.node.peer_tls import client_ssl_context
from node_helpers import create_identities, free_port, network_config, provision_peers, running_peer

FAST_TIMING = PeerTiming(
    connected_interval_seconds=0.2,
    retry_min_seconds=0.05,
    retry_max_seconds=0.2,
    request_timeout_seconds=3.0,
)


def _state(monitor: PeerMonitor, node_id: str) -> str:
    return next(status.state for status in monitor.snapshot() if status.node_id == node_id)


def _status(monitor: PeerMonitor, node_id: str) -> PeerStatus:
    return next(status for status in monitor.snapshot() if status.node_id == node_id)


async def _wait_until(condition: Callable[[], bool], timeout: float = 15.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not condition():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("The condition was not met in time.")
        await asyncio.sleep(0.05)


def _monitor(
    identity: NodeIdentity,
    config,
    peer_node: str,
    peer_port: int,
    trusted: dict[str, Path],
) -> PeerMonitor:
    return PeerMonitor(
        identity=identity,
        shared_config=config,
        peers=(PeerAddress(node_id=peer_node, host="127.0.0.1", port=peer_port),),
        trusted_certificates=trusted,
        timing=FAST_TIMING,
    )


def test_two_nodes_connect_with_mutual_authentication(tmp_path: Path) -> None:
    identities = create_identities(tmp_path, ["node-a", "node-b"])
    config = network_config(identities)
    certs_a = provision_peers(identities, config, "node-a", ["node-b"])
    certs_b = provision_peers(identities, config, "node-b", ["node-a"])
    port_a, port_b = free_port(), free_port()
    stack = ExitStack()
    stack.enter_context(running_peer(identities["node-a"], config, port_a, certs_a, tmp_path / "data-a"))
    stack.enter_context(running_peer(identities["node-b"], config, port_b, certs_b, tmp_path / "data-b"))
    try:

        async def scenario() -> None:
            monitor_a = _monitor(identities["node-a"], config, "node-b", port_b, certs_a)
            monitor_b = _monitor(identities["node-b"], config, "node-a", port_a, certs_b)
            tasks = [asyncio.create_task(monitor_a.run()), asyncio.create_task(monitor_b.run())]
            try:
                await _wait_until(lambda: _state(monitor_a, "node-b") == "connected")
                await _wait_until(lambda: _state(monitor_b, "node-a") == "connected")
                assert _status(monitor_a, "node-b").detail == "Connected and verified."
            finally:
                for task in tasks:
                    task.cancel()

        asyncio.run(scenario())
    finally:
        stack.close()


def test_unknown_node_with_valid_certificate_is_rejected(tmp_path: Path) -> None:
    identities = create_identities(tmp_path, ["node-a", "node-b"])
    config = network_config(identities)
    certs_b = provision_peers(identities, config, "node-b", ["node-a"])
    port_b = free_port()
    stack = ExitStack()
    stack.enter_context(running_peer(identities["node-b"], config, port_b, certs_b, tmp_path / "data-b"))
    try:
        outsider = create_node_identity(tmp_path / "outsider", "node-x")
        context = client_ssl_context(outsider, identities["node-b"].certificate_path)

        async def attempt() -> None:
            with pytest.raises(PeerRejectedError):
                await fetch_peer_hello(
                    PeerAddress(node_id="node-b", host="127.0.0.1", port=port_b), context, timeout_seconds=3.0
                )

        asyncio.run(attempt())
    finally:
        stack.close()


@pytest.mark.parametrize(
    ("overrides", "expected_detail"),
    [
        ({"network_id": "other-network"}, "different network ID"),
        ({"protocol_version": 2}, "different protocol version"),
        ({"genesis_timestamp": "2026-02-01T00:00:00Z"}, "different genesis hash"),
    ],
)
def test_incompatible_peer_is_rejected(tmp_path: Path, overrides: dict, expected_detail: str) -> None:
    identities = create_identities(tmp_path, ["node-a", "node-b"])
    config_a = network_config(identities)
    config_b = network_config(identities, **overrides)
    certs_a = provision_peers(identities, config_a, "node-a", ["node-b"])
    certs_b = provision_peers(identities, config_b, "node-b", ["node-a"])
    port_b = free_port()
    stack = ExitStack()
    stack.enter_context(running_peer(identities["node-b"], config_b, port_b, certs_b, tmp_path / "data-b"))
    try:

        async def scenario() -> None:
            monitor = _monitor(identities["node-a"], config_a, "node-b", port_b, certs_a)
            task = asyncio.create_task(monitor.run())
            try:
                await _wait_until(lambda: _state(monitor, "node-b") == "rejected")
                assert expected_detail in _status(monitor, "node-b").detail
            finally:
                task.cancel()

        asyncio.run(scenario())
    finally:
        stack.close()


def test_unavailable_peer_is_reported_without_stopping_monitor(tmp_path: Path) -> None:
    identities = create_identities(tmp_path, ["node-a", "node-b"])
    config = network_config(identities)
    certs_a = provision_peers(identities, config, "node-a", ["node-b"])

    async def scenario() -> None:
        monitor = _monitor(identities["node-a"], config, "node-b", free_port(), certs_a)
        task = asyncio.create_task(monitor.run())
        try:
            await _wait_until(lambda: _state(monitor, "node-b") == "unreachable")
            assert not task.done()
        finally:
            task.cancel()

    asyncio.run(scenario())


def test_peer_without_imported_certificate_is_reported(tmp_path: Path) -> None:
    identities = create_identities(tmp_path, ["node-a", "node-b"])
    config = network_config(identities)
    monitor = _monitor(identities["node-a"], config, "node-b", free_port(), {})

    async def scenario() -> None:
        task = asyncio.create_task(monitor.run())
        try:
            await _wait_until(lambda: _state(monitor, "node-b") == "certificate_missing")
        finally:
            task.cancel()

    asyncio.run(scenario())


def test_status_follows_peer_going_offline(tmp_path: Path) -> None:
    identities = create_identities(tmp_path, ["node-a", "node-b"])
    config = network_config(identities)
    certs_a = provision_peers(identities, config, "node-a", ["node-b"])
    certs_b = provision_peers(identities, config, "node-b", ["node-a"])
    port_b = free_port()
    stack = ExitStack()
    stack.enter_context(running_peer(identities["node-b"], config, port_b, certs_b, tmp_path / "data-b"))

    async def scenario() -> None:
        monitor = _monitor(identities["node-a"], config, "node-b", port_b, certs_a)
        task = asyncio.create_task(monitor.run())
        try:
            await _wait_until(lambda: _state(monitor, "node-b") == "connected")
            stack.close()
            await _wait_until(lambda: _state(monitor, "node-b") == "unreachable")
        finally:
            task.cancel()

    asyncio.run(scenario())
