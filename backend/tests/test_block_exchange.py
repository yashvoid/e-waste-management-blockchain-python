import asyncio
import dataclasses
from collections.abc import Callable
from pathlib import Path

import pytest

from app.blockchain.structures import Block
from app.config.node_settings import PeerAddress
from app.node import chain_sync
from app.node.chain_sync import ChainSynchronizer
from app.node.peer_client import PeerRejectedError, PeerUnavailableError, fetch_blocks_after, fetch_peer_tip
from app.node.peer_monitor import PeerMonitor, PeerTiming
from app.node.peer_tls import client_ssl_context
from app.node.pending_pool import PendingTransactionPool
from app.storage.chain_storage import ChainStorage, open_chain_storage
from app.storage.record_files import read_complete_records
from chain_helpers import key_for_label, mine, sign_transaction
from node_helpers import create_identities, free_port, network_config, provision_peers, running_peer

TIMING = PeerTiming(
    connected_interval_seconds=0.2,
    retry_min_seconds=0.05,
    retry_max_seconds=0.2,
    request_timeout_seconds=5.0,
    block_request_timeout_seconds=10.0,
)


def _ts(index: int) -> str:
    return f"2026-01-01T{index // 60:02d}:{index % 60:02d}:00Z"


def _extend(storage: ChainStorage, label: str, count: int) -> list[Block]:
    blocks: list[Block] = []
    for offset in range(count):
        index = storage.store.tip.height + 1
        tx = sign_transaction(storage.config, key_for_label(label), _ts(index), payload={"branch": label, "n": index})
        block = mine(storage.config, storage.store.tip, [tx], _ts(index))
        storage.add_block(block)
        blocks.append(block)
    return blocks


def _records(data_dir: Path) -> int:
    return len(read_complete_records(data_dir))


def _pair(tmp_path: Path):
    identities = create_identities(tmp_path, ["node-a", "node-b"])
    config = network_config(identities)
    certs_a = provision_peers(identities, config, "node-a", ["node-b"])
    certs_b = provision_peers(identities, config, "node-b", ["node-a"])
    return identities, config, certs_a, certs_b


def _synchronizer(storage: ChainStorage, identity, peer_certs: dict[str, Path]) -> ChainSynchronizer:
    contexts = {node_id: client_ssl_context(identity, path) for node_id, path in peer_certs.items()}
    return ChainSynchronizer(
        chain_storage=storage,
        shared_config=storage.config,
        contexts=contexts,
        timing=TIMING,
        pool=PendingTransactionPool(storage),
    )


def _address(node_id: str, port: int) -> PeerAddress:
    return PeerAddress(node_id=node_id, host="127.0.0.1", port=port)


def test_tip_endpoint_reports_chain_information(tmp_path: Path) -> None:
    identities, config, certs_a, certs_b = _pair(tmp_path)
    port_a = free_port()
    with running_peer(identities["node-a"], config, port_a, certs_a, tmp_path / "data-a") as storage_a:
        _extend(storage_a, "a", 3)

        async def scenario():
            return await fetch_peer_tip(_address("node-a", port_a), client_ssl_context(identities["node-b"], certs_b["node-a"]), 5.0)

        tip = asyncio.run(scenario())
        assert tip.tip_hash == storage_a.store.tip.block_hash
        assert tip.height == 3
        assert tip.cumulative_work == storage_a.store.cumulative_work(storage_a.store.tip)
        assert tip.hello.node_id == "node-a"


def test_behind_node_downloads_missing_blocks_in_batches(tmp_path: Path) -> None:
    identities, config, certs_a, certs_b = _pair(tmp_path)
    port_a = free_port()
    data_b = tmp_path / "data-b"
    with running_peer(identities["node-a"], config, port_a, certs_a, tmp_path / "data-a") as storage_a:
        _extend(storage_a, "a", 10)
        with open_chain_storage(data_b, config) as storage_b:
            sync = _synchronizer(storage_b, identities["node-b"], certs_b)
            outcome = asyncio.run(sync.sync_peer(_address("node-a", port_a)))
            assert outcome.state == "synchronized"
            assert outcome.blocks_received == 10
            assert storage_b.store.tip.block_hash == storage_a.store.tip.block_hash
            assert _records(data_b) == 11


def test_repeated_sync_is_up_to_date_and_writes_nothing(tmp_path: Path) -> None:
    identities, config, certs_a, certs_b = _pair(tmp_path)
    port_a = free_port()
    data_b = tmp_path / "data-b"
    with running_peer(identities["node-a"], config, port_a, certs_a, tmp_path / "data-a") as storage_a:
        _extend(storage_a, "a", 3)
        with open_chain_storage(data_b, config) as storage_b:
            sync = _synchronizer(storage_b, identities["node-b"], certs_b)
            asyncio.run(sync.sync_peer(_address("node-a", port_a)))
            records_after_first = _records(data_b)
            outcome = asyncio.run(sync.sync_peer(_address("node-a", port_a)))
            assert outcome.state == "up_to_date"
            assert _records(data_b) == records_after_first


def test_longer_competing_branch_replaces_canonical_chain(tmp_path: Path) -> None:
    identities, config, certs_a, certs_b = _pair(tmp_path)
    port_a = free_port()
    data_b = tmp_path / "data-b"
    with running_peer(identities["node-a"], config, port_a, certs_a, tmp_path / "data-a") as storage_a:
        _extend(storage_a, "a", 3)
        with open_chain_storage(data_b, config) as storage_b:
            local_branch = _extend(storage_b, "b", 2)
            sync = _synchronizer(storage_b, identities["node-b"], certs_b)
            outcome = asyncio.run(sync.sync_peer(_address("node-a", port_a)))
            assert outcome.state == "synchronized"
            assert storage_b.store.tip.block_hash == storage_a.store.tip.block_hash
            assert outcome.removed_transactions == 2
            assert outcome.newly_confirmed_transactions == 3
            assert all(block.block_hash in storage_b.store.blocks_by_hash for block in local_branch)


def test_equal_work_tie_is_resolved_by_lowest_tip_hash(tmp_path: Path) -> None:
    identities, config, certs_a, certs_b = _pair(tmp_path)
    port_a = free_port()
    data_b = tmp_path / "data-b"
    with running_peer(identities["node-a"], config, port_a, certs_a, tmp_path / "data-a") as storage_a:
        _extend(storage_a, "a", 2)
        with open_chain_storage(data_b, config) as storage_b:
            _extend(storage_b, "b", 2)
            local_tip = storage_b.store.tip.block_hash
            remote_tip = storage_a.store.tip.block_hash
            sync = _synchronizer(storage_b, identities["node-b"], certs_b)
            asyncio.run(sync.sync_peer(_address("node-a", port_a)))
            assert storage_b.store.tip.block_hash == min(local_tip, remote_tip)


def test_invalid_block_from_peer_is_rejected_without_storing_it(tmp_path: Path, monkeypatch) -> None:
    identities, config, certs_a, certs_b = _pair(tmp_path)
    port_a = free_port()
    data_b = tmp_path / "data-b"
    original = chain_sync.fetch_blocks_after

    async def tampered(*args, **kwargs):
        blocks = await original(*args, **kwargs)
        return [dataclasses.replace(blocks[0], nonce=blocks[0].nonce + 1)] + blocks[1:]

    with running_peer(identities["node-a"], config, port_a, certs_a, tmp_path / "data-a") as storage_a:
        _extend(storage_a, "a", 2)
        with open_chain_storage(data_b, config) as storage_b:
            monkeypatch.setattr(chain_sync, "fetch_blocks_after", tampered)
            sync = _synchronizer(storage_b, identities["node-b"], certs_b)
            outcome = asyncio.run(sync.sync_peer(_address("node-a", port_a)))
            assert outcome.state == "invalid_data"
            assert _records(data_b) == 1
            assert storage_b.store.tip.height == 0


@pytest.mark.parametrize(
    ("overrides", "expected_detail"),
    [({"network_id": "other-network"}, "different network ID"), ({"protocol_version": 2}, "different protocol version")],
)
def test_incompatible_peer_blocks_are_not_downloaded(tmp_path: Path, overrides: dict, expected_detail: str) -> None:
    identities = create_identities(tmp_path, ["node-a", "node-b"])
    config_a = network_config(identities)
    config_b = network_config(identities, **overrides)
    certs_a = provision_peers(identities, config_a, "node-a", ["node-b"])
    certs_b = provision_peers(identities, config_b, "node-b", ["node-a"])
    port_b = free_port()
    with running_peer(identities["node-b"], config_b, port_b, certs_b, tmp_path / "data-b") as storage_b:
        _extend(storage_b, "b", 2)
        with open_chain_storage(tmp_path / "data-a", config_a) as storage_a:
            sync = _synchronizer(storage_a, identities["node-a"], certs_a)
            outcome = asyncio.run(sync.sync_peer(_address("node-b", port_b)))
            assert outcome.state == "rejected"
            assert expected_detail in outcome.detail
            assert storage_a.store.tip.height == 0


def test_unavailable_peer_returns_outcome_without_raising(tmp_path: Path) -> None:
    identities, config, certs_a, _ = _pair(tmp_path)
    with open_chain_storage(tmp_path / "data-a", config) as storage_a:
        sync = _synchronizer(storage_a, identities["node-a"], certs_a)
        outcome = asyncio.run(sync.sync_peer(_address("node-b", free_port())))
        assert outcome.state == "unavailable"


def test_interrupted_download_keeps_valid_blocks_and_resumes(tmp_path: Path, monkeypatch) -> None:
    identities, config, certs_a, certs_b = _pair(tmp_path)
    port_a = free_port()
    data_b = tmp_path / "data-b"
    original = chain_sync.fetch_blocks_after
    calls = {"count": 0}

    async def interrupted(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 2:
            raise PeerUnavailableError("The peer did not respond in time.")
        return await original(*args, **kwargs)

    with running_peer(identities["node-a"], config, port_a, certs_a, tmp_path / "data-a") as storage_a:
        _extend(storage_a, "a", 10)
        with open_chain_storage(data_b, config) as storage_b:
            sync = _synchronizer(storage_b, identities["node-b"], certs_b)
            monkeypatch.setattr(chain_sync, "fetch_blocks_after", interrupted)
            outcome = asyncio.run(sync.sync_peer(_address("node-a", port_a)))
            assert outcome.state == "unavailable"
            assert storage_b.store.tip.height == 8
            monkeypatch.setattr(chain_sync, "fetch_blocks_after", original)
            outcome = asyncio.run(sync.sync_peer(_address("node-a", port_a)))
            assert outcome.state == "synchronized"
            assert storage_b.store.tip.block_hash == storage_a.store.tip.block_hash
            assert _records(data_b) == 11


def test_oversized_or_overlong_block_responses_are_refused(tmp_path: Path) -> None:
    identities, config, certs_a, certs_b = _pair(tmp_path)
    port_a = free_port()
    with running_peer(identities["node-a"], config, port_a, certs_a, tmp_path / "data-a") as storage_a:
        blocks = _extend(storage_a, "a", 2)
        context = client_ssl_context(identities["node-b"], certs_b["node-a"])
        address = _address("node-a", port_a)

        async def scenario() -> None:
            with pytest.raises(PeerRejectedError):
                await fetch_blocks_after(address, context, 5.0, blocks[0].block_hash, 1, max_bytes=50)
            with pytest.raises(PeerRejectedError):
                await fetch_blocks_after(address, context, 5.0, storage_a.store.blocks_by_hash[blocks[0].previous_hash].block_hash, 9, max_bytes=10_000_000)

        asyncio.run(scenario())


def test_duplicate_blocks_are_ignored_by_storage(tmp_path: Path) -> None:
    _, config, _, _ = _pair(tmp_path)
    data = tmp_path / "data"
    with open_chain_storage(data, config) as storage:
        blocks = _extend(storage, "a", 3)
        before = _records(data)
        storage.add_blocks(blocks)
        assert _records(data) == before
        assert storage.store.tip.height == 3


def test_synchronized_chain_survives_restart(tmp_path: Path) -> None:
    identities, config, certs_a, certs_b = _pair(tmp_path)
    port_a = free_port()
    data_b = tmp_path / "data-b"
    with running_peer(identities["node-a"], config, port_a, certs_a, tmp_path / "data-a") as storage_a:
        _extend(storage_a, "a", 4)
        with open_chain_storage(data_b, config) as storage_b:
            asyncio.run(_synchronizer(storage_b, identities["node-b"], certs_b).sync_peer(_address("node-a", port_a)))
            tip = storage_b.store.tip.block_hash
        with open_chain_storage(data_b, config) as reopened:
            assert reopened.store.tip.block_hash == tip


def test_reconnecting_peer_triggers_synchronization(tmp_path: Path) -> None:
    identities, config, certs_a, certs_b = _pair(tmp_path)
    port_a = free_port()
    data_b = tmp_path / "data-b"
    with open_chain_storage(data_b, config) as storage_b, running_peer(
        identities["node-a"], config, port_a, certs_a, tmp_path / "data-a"
    ) as storage_a:
        _extend(storage_a, "a", 3)
        sync = _synchronizer(storage_b, identities["node-b"], certs_b)
        monitor = PeerMonitor(
            identity=identities["node-b"],
            shared_config=config,
            peers=(_address("node-a", port_a),),
            trusted_certificates=certs_b,
            timing=TIMING,
            on_connected=sync.sync_peer,
        )

        async def scenario() -> None:
            task = asyncio.create_task(monitor.run())
            try:
                deadline = asyncio.get_running_loop().time() + 15
                while storage_b.store.tip.block_hash != storage_a.store.tip.block_hash:
                    assert asyncio.get_running_loop().time() < deadline, "Synchronization did not complete."
                    await asyncio.sleep(0.05)
            finally:
                task.cancel()

        asyncio.run(scenario())


def test_cancelling_monitor_stops_background_synchronization(tmp_path: Path) -> None:
    identities, config, certs_a, certs_b = _pair(tmp_path)
    port_a = free_port()
    with running_peer(identities["node-a"], config, port_a, certs_a, tmp_path / "data-a"):
        entered: list[bool] = []

        async def never_finishes(peer: PeerAddress) -> None:
            entered.append(True)
            await asyncio.Event().wait()

        monitor = PeerMonitor(
            identity=identities["node-b"],
            shared_config=config,
            peers=(_address("node-a", port_a),),
            trusted_certificates=certs_b,
            timing=TIMING,
            on_connected=never_finishes,
        )

        async def scenario() -> None:
            task = asyncio.create_task(monitor.run())
            deadline = asyncio.get_running_loop().time() + 15
            while not entered:
                assert asyncio.get_running_loop().time() < deadline
                await asyncio.sleep(0.05)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            assert task.cancelled()

        asyncio.run(scenario())
