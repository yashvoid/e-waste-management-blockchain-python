import dataclasses
import json
import time
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path

import httpx
import pytest

from app.config.node_settings import PeerAddress
from app.config.shared_network import SharedNetworkConfig
from app.node.peer_tls import client_ssl_context
from chain_helpers import key_for_label, mine, sign_transaction
from node_helpers import create_identities, free_port, network_config, provision_peers, running_node

WAIT_SECONDS = 10.0


def _ts(index: int) -> str:
    return f"2026-01-01T{index // 60:02d}:{index % 60:02d}:00Z"


def _tx(config: SharedNetworkConfig, label: str, index: int):
    return sign_transaction(config, key_for_label(label), _ts(index), payload={"n": index})


def _address(node_id: str, port: int) -> PeerAddress:
    return PeerAddress(node_id=node_id, host="127.0.0.1", port=port)


def _wait_for(predicate: Callable[[], bool], timeout_seconds: float = WAIT_SECONDS) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def _start(
    stack: ExitStack,
    identities: dict,
    config: SharedNetworkConfig,
    data_root: Path,
    node_id: str,
    port: int,
    peers: list[PeerAddress] | None = None,
    trusted_ids: list[str] | None = None,
):
    if trusted_ids is None:
        trusted_ids = [other for other in identities if other != node_id]
    certs = provision_peers(identities, config, node_id, trusted_ids)
    return stack.enter_context(
        running_node(identities[node_id], config, port, certs, data_root / node_id, tuple(peers or ()))
    )


def test_submitted_transaction_reaches_connected_peer(tmp_path: Path) -> None:
    identities = create_identities(tmp_path, ["node-a", "node-b"])
    config = network_config(identities)
    port_a, port_b = free_port(), free_port()
    with ExitStack() as stack:
        a = _start(stack, identities, config, tmp_path / "data", "node-a", port_a, [_address("node-b", port_b)])
        b = _start(stack, identities, config, tmp_path / "data", "node-b", port_b, [_address("node-a", port_a)])
        tx = _tx(config, "alice", 1)
        assert a.relay.submit_local(tx).state == "accepted"
        assert _wait_for(lambda: b.pool.get(tx.txid) is not None)


def test_transaction_relays_across_an_intermediate_peer(tmp_path: Path) -> None:
    identities = create_identities(tmp_path, ["node-a", "node-b", "node-c"])
    config = network_config(identities)
    port_a, port_b, port_c = free_port(), free_port(), free_port()
    with ExitStack() as stack:
        a = _start(stack, identities, config, tmp_path / "data", "node-a", port_a, [_address("node-b", port_b)])
        b = _start(
            stack,
            identities,
            config,
            tmp_path / "data",
            "node-b",
            port_b,
            [_address("node-a", port_a), _address("node-c", port_c)],
        )
        c = _start(stack, identities, config, tmp_path / "data", "node-c", port_c, [_address("node-b", port_b)])
        tx = _tx(config, "bob", 2)
        assert a.relay.submit_local(tx).state == "accepted"
        assert _wait_for(lambda: b.pool.get(tx.txid) is not None)
        assert _wait_for(lambda: c.pool.get(tx.txid) is not None)


def test_duplicate_announcements_are_suppressed(tmp_path: Path) -> None:
    identities = create_identities(tmp_path, ["node-a", "node-b"])
    config = network_config(identities)
    port_a, port_b = free_port(), free_port()
    with ExitStack() as stack:
        a = _start(stack, identities, config, tmp_path / "data", "node-a", port_a, [_address("node-b", port_b)])
        b = _start(stack, identities, config, tmp_path / "data", "node-b", port_b, [_address("node-a", port_a)])
        tx = _tx(config, "carol", 3)
        assert a.relay.submit_local(tx).state == "accepted"
        assert _wait_for(lambda: b.pool.get(tx.txid) is not None)
        assert b.relay.receive(tx, "node-a").state == "known"
        assert a.relay.submit_local(tx).state == "known"
        assert len(b.pool.ordered()) == 1


def test_transaction_is_delivered_when_peer_comes_online(tmp_path: Path) -> None:
    identities = create_identities(tmp_path, ["node-a", "node-b"])
    config = network_config(identities)
    port_a, port_b = free_port(), free_port()
    with ExitStack() as stack:
        a = _start(stack, identities, config, tmp_path / "data", "node-a", port_a, [_address("node-b", port_b)])
        tx = _tx(config, "dave", 4)
        assert a.relay.submit_local(tx).state == "accepted"
        time.sleep(1.5)
        b = _start(stack, identities, config, tmp_path / "data", "node-b", port_b, [_address("node-a", port_a)])
        assert b.pool.get(tx.txid) is None
        a.relay.send_pending_to(_address("node-b", port_b))
        assert _wait_for(lambda: b.pool.get(tx.txid) is not None)


def test_client_without_trusted_certificate_cannot_post(tmp_path: Path) -> None:
    identities = create_identities(tmp_path, ["node-a", "node-b", "node-x"])
    config = network_config({key: identities[key] for key in ("node-a", "node-b")})
    port_b = free_port()
    with ExitStack() as stack:
        b = _start(stack, identities, config, tmp_path / "data", "node-b", port_b, trusted_ids=["node-a"])
        tx = _tx(config, "erin", 5)
        context = client_ssl_context(identities["node-x"], identities["node-b"].certificate_path)
        body = json.dumps({"transaction": tx.to_dict(), "originNodeId": None}).encode("utf-8")
        with httpx.Client(verify=context, timeout=3.0) as client:
            with pytest.raises(httpx.HTTPError):
                client.post(
                    f"https://127.0.0.1:{port_b}/peer/transactions",
                    content=body,
                    headers={"Content-Type": "application/json"},
                )
        assert b.pool.ordered() == ()


def test_transaction_from_another_network_is_rejected(tmp_path: Path) -> None:
    identities = create_identities(tmp_path, ["node-a", "node-b"])
    config = network_config(identities)
    other_config = network_config(identities, network_id="other-network")
    port_b = free_port()
    with ExitStack() as stack:
        b = _start(stack, identities, config, tmp_path / "data", "node-b", port_b)
        certs = provision_peers(identities, config, "node-a", ["node-b"])
        context = client_ssl_context(identities["node-a"], certs["node-b"])
        tx = _tx(other_config, "frank", 6)
        body = json.dumps({"transaction": tx.to_dict(), "originNodeId": "node-a"}).encode("utf-8")
        with httpx.Client(verify=context, timeout=3.0) as client:
            response = client.post(
                f"https://127.0.0.1:{port_b}/peer/transactions",
                content=body,
                headers={"Content-Type": "application/json"},
            )
        assert response.status_code == 200
        assert response.json()["result"] == "rejected"
        assert b.pool.ordered() == ()


def test_invalid_transaction_is_not_relayed(tmp_path: Path) -> None:
    identities = create_identities(tmp_path, ["node-a", "node-b"])
    config = network_config(identities)
    port_a, port_b = free_port(), free_port()
    with ExitStack() as stack:
        a = _start(stack, identities, config, tmp_path / "data", "node-a", port_a, [_address("node-b", port_b)])
        b = _start(stack, identities, config, tmp_path / "data", "node-b", port_b, [_address("node-a", port_a)])
        genuine = _tx(config, "gina", 7)
        forged = dataclasses.replace(genuine, signature=_tx(config, "hank", 8).signature)
        assert a.relay.submit_local(forged).state == "rejected"
        time.sleep(1.0)
        assert b.pool.ordered() == ()
        assert a.pool.ordered() == ()


def test_confirmed_transaction_leaves_pending_pool(tmp_path: Path) -> None:
    identities = create_identities(tmp_path, ["node-a", "node-b"])
    config = network_config(identities)
    port_a = free_port()
    with ExitStack() as stack:
        a = _start(stack, identities, config, tmp_path / "data", "node-a", port_a, [_address("node-b", free_port())])
        tx = _tx(config, "ivy", 9)
        assert a.relay.submit_local(tx).state == "accepted"
        a.storage.add_block(mine(config, a.storage.store.tip, [tx], _ts(9)))
        a.pool.reconcile([])
        assert a.pool.get(tx.txid) is None
        assert a.relay.submit_local(tx).state == "confirmed"
