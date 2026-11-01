import copy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.application import router
from app.blockchain.processing import material_id_for
from app.config.shared_network import SharedNetworkConfig, TrustEpoch, TrustedNode
from app.node.pending_pool import PendingTransactionPool
from app.storage.chain_storage import open_chain_storage
from business_helpers import (
    COL,
    GEN,
    MP,
    REC,
    TRA,
    accept_tx,
    at,
    batch_tx,
    cancel_tx,
    correction_tx,
    make_network,
    process_tx,
    register_tx,
    reject_tx,
    request_tx,
    wallet_key,
    wallet_pub,
)
from chain_helpers import mine, shared_network_values, sign_transaction, key_for_label
from node_helpers import attestation_public_key_for, create_identities
from app.blockchain.participants import REGISTER_TYPE
from app.node.attestation import PURPOSE_REGISTRATION, issue_attestation


@pytest.fixture
def network(tmp_path: Path):
    return make_network(tmp_path)


@pytest.fixture
def network_now(tmp_path: Path):
    identities = create_identities(tmp_path, ["node-a", "node-b"])
    genesis_ts = (datetime.now(UTC) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    values = shared_network_values(1, genesis_timestamp=genesis_ts)
    listed = tuple(
        TrustedNode(
            node_id,
            identity.certificate_sha256,
            attestation_public_key_for(identity),
            "active",
        )
        for node_id, identity in identities.items()
    )
    config = replace(
        SharedNetworkConfig(**{**values, "trust_epochs": ()}),
        trust_epochs=(TrustEpoch(0, 0, listed),),
    )
    return identities, config


@pytest.fixture
def app_client(tmp_path: Path, network):
    _, config = network
    app = FastAPI()
    app.include_router(router)
    with open_chain_storage(tmp_path / "chain", config) as storage:
        pool = PendingTransactionPool(storage)
        app.state.chain_storage = storage
        app.state.shared_network = config
        app.state.transaction_relay = SimpleNamespace(pool=pool, submit_local=pool.admit)
        yield SimpleNamespace(client=TestClient(app), storage=storage, config=config, pool=pool)


@pytest.fixture
def app_client_now(tmp_path: Path, network_now):
    _, config = network_now
    app = FastAPI()
    app.include_router(router)
    with open_chain_storage(tmp_path / "chain", config) as storage:
        pool = PendingTransactionPool(storage)
        app.state.chain_storage = storage
        app.state.shared_network = config
        app.state.transaction_relay = SimpleNamespace(pool=pool, submit_local=pool.admit)
        yield SimpleNamespace(client=TestClient(app), storage=storage, config=config, pool=pool)


def _confirm(app_client, transactions, when):
    _, config = app_client.config, None
    config = app_client.config
    block = mine(config, app_client.storage.store.tip, transactions, when)
    app_client.storage.add_block(block)
    return block


def _register_all(app_client, network):
    _, config = network
    registrations = [
        register_tx(network, GEN, "Generator"),
        register_tx(network, COL, "Collector"),
        register_tx(network, TRA, "Transporter"),
        register_tx(network, REC, "Recycler"),
        register_tx(network, MP, "Material Processor"),
    ]
    _confirm(app_client, registrations, at(minutes=1))


def _register_all_now(app_client_now, network_now):
    identities, config = network_now
    issued = _now_str(-35)
    registrations = []
    for label, role in [
        (GEN, "Generator"),
        (COL, "Collector"),
        (TRA, "Transporter"),
        (REC, "Recycler"),
        (MP, "Material Processor"),
    ]:
        attestation = issue_attestation(
            identities["node-a"].key_path.parent,
            config,
            node_id="node-a",
            purpose=PURPOSE_REGISTRATION,
            wallet_public_key=wallet_pub(label),
            role=role,
            request_id=f"req-{label}",
            nonce=f"reg-{label}",
            issued_at=issued,
        )
        tx = sign_transaction(
            config,
            wallet_key(label),
            issued,
            payload={"attestation": attestation.to_dict()},
            nonce=0,
            tx_type=REGISTER_TYPE,
        )
        registrations.append(tx)
    _confirm(app_client_now, registrations, _now_str(-30))


def _deliver_to_recycler(app_client, network, grams=100_000):
    _, config = network
    batch = batch_tx(config, GEN, grams)
    _confirm(app_client, [batch], at(minutes=2))
    hops = ((GEN, COL), (COL, TRA), (TRA, REC))
    for step, (sender, receiver) in enumerate(hops):
        request = request_tx(config, sender, batch.txid, receiver, grams, nonce=step)
        _confirm(app_client, [request], at(minutes=3 + step * 2))
        _confirm(app_client, [accept_tx(config, receiver, request.txid, grams)], at(minutes=4 + step * 2))
    return batch.txid


def _transfer_material(app_client, network, material_id, grams, minute, nonce=0):
    _, config = network
    request = request_tx(config, REC, material_id, MP, grams, nonce=nonce)
    _confirm(app_client, [request], at(minutes=minute))
    _confirm(app_client, [accept_tx(config, MP, request.txid, grams)], at(minutes=minute + 1))
    return request.txid


def _deliver_to_recycler_now(app_client, network, grams=100_000):
    _, config = network
    batch = batch_tx(config, GEN, grams)
    _confirm(app_client, [batch], _now_str(-20))
    hops = ((GEN, COL), (COL, TRA), (TRA, REC))
    for step, (sender, receiver) in enumerate(hops):
        request = request_tx(config, sender, batch.txid, receiver, grams, nonce=step)
        _confirm(app_client, [request], _now_str(-18 + step * 4))
        _confirm(app_client, [accept_tx(config, receiver, request.txid, grams)], _now_str(-16 + step * 4))
    return batch.txid


# ---------------------------------------------------------------------------
# Empty chain
# ---------------------------------------------------------------------------


def test_empty_chain_returns_no_batches(app_client):
    response = app_client.client.get("/api/app/batches")
    assert response.status_code == 200
    assert response.json() == {"batches": []}


def test_empty_chain_returns_no_materials(app_client):
    response = app_client.client.get("/api/app/materials")
    assert response.status_code == 200
    assert response.json() == {"materials": []}


def test_empty_chain_returns_no_operations(app_client):
    response = app_client.client.get("/api/app/processing")
    assert response.status_code == 200
    assert response.json() == {"operations": []}


def test_empty_chain_returns_genesis_tip(app_client):
    response = app_client.client.get("/api/app/chain")
    assert response.status_code == 200
    body = response.json()
    assert body["tipHeight"] == 0
    assert body["networkId"] == "test-network"
    assert body["protocolVersion"] == 1


# ---------------------------------------------------------------------------
# Batch listing and details
# ---------------------------------------------------------------------------


def test_batch_list_shows_confirmed_batch(app_client, network):
    _register_all(app_client, network)
    _, config = network
    batch = batch_tx(config, GEN, 50_000, description="Old monitors")
    _confirm(app_client, [batch], at(minutes=2))
    response = app_client.client.get("/api/app/batches")
    assert response.status_code == 200
    batches = response.json()["batches"]
    assert len(batches) == 1
    assert batches[0]["batchId"] == batch.txid
    assert batches[0]["description"] == "Old monitors"
    assert batches[0]["quantityGrams"] == 50_000
    assert batches[0]["quantityKg"] == 50.0


def test_batch_detail_returns_full_information(app_client, network):
    _register_all(app_client, network)
    _, config = network
    batch = batch_tx(config, GEN, 100_000)
    _confirm(app_client, [batch], at(minutes=2))
    response = app_client.client.get(f"/api/app/batches/{batch.txid}")
    assert response.status_code == 200
    body = response.json()
    assert body["batchId"] == batch.txid
    assert body["generator"] == wallet_pub(GEN)
    assert body["quantityGrams"] == 100_000
    assert body["completion"]["completed"] is False
    assert body["completion"]["remainingGrams"] == 100_000


def test_unknown_batch_returns_404(app_client):
    response = app_client.client.get("/api/app/batches/nonexistent-id")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Transfers
# ---------------------------------------------------------------------------


def test_batch_transfers_show_pending_and_confirmed(app_client, network):
    _register_all(app_client, network)
    _, config = network
    batch_id = _deliver_to_recycler(app_client, network, 100_000)
    # Create a new pending transfer from recycler to material processor on a material
    op = process_tx(config, REC, batch_id, 100_000, [("Copper", 100_000)], 0)
    _confirm(app_client, [op], at(minutes=10))
    material_id = material_id_for(op.txid, 0)
    request = request_tx(config, REC, material_id, MP, 100_000)
    _confirm(app_client, [request], at(minutes=11))

    # The batch transfers should show the accepted custody transfers
    response = app_client.client.get(f"/api/app/batches/{batch_id}/transfers")
    assert response.status_code == 200
    transfers = response.json()["transfers"]
    assert len(transfers) == 3
    statuses = [t["status"] for t in transfers]
    assert all(s == "accepted" for s in statuses)
    assert transfers[0]["sender"] == wallet_pub(GEN)
    assert transfers[0]["receiver"] == wallet_pub(COL)
    assert transfers[0]["declaredGrams"] == 100_000
    assert transfers[0]["actualGrams"] == 100_000


def test_batch_transfers_include_pending_status(app_client, network):
    _register_all(app_client, network)
    _, config = network
    batch = batch_tx(config, GEN, 100_000)
    _confirm(app_client, [batch], at(minutes=2))
    request = request_tx(config, GEN, batch.txid, COL, 40_000)
    _confirm(app_client, [request], at(minutes=3))
    response = app_client.client.get(f"/api/app/batches/{batch.txid}/transfers")
    assert response.status_code == 200
    transfers = response.json()["transfers"]
    assert len(transfers) == 1
    assert transfers[0]["status"] == "pending"
    assert transfers[0]["actualGrams"] is None


def test_transfers_for_unknown_batch_returns_404(app_client):
    response = app_client.client.get("/api/app/batches/unknown/transfers")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Materials and processing
# ---------------------------------------------------------------------------


def test_material_list_shows_recovered_materials(app_client, network):
    _register_all(app_client, network)
    _, config = network
    batch_id = _deliver_to_recycler(app_client, network)
    op = process_tx(config, REC, batch_id, 100_000, [("Copper", 70_000), ("Plastic", 30_000)], 0)
    _confirm(app_client, [op], at(minutes=10))
    response = app_client.client.get("/api/app/materials")
    assert response.status_code == 200
    materials = response.json()["materials"]
    assert len(materials) == 2
    assert materials[0]["description"] == "Copper"
    assert materials[0]["quantityGrams"] == 70_000
    assert materials[0]["parentItem"] == batch_id
    assert materials[0]["sourceOperation"] == op.txid


def test_material_detail_returns_completion(app_client, network):
    _register_all(app_client, network)
    _, config = network
    batch_id = _deliver_to_recycler(app_client, network)
    op = process_tx(config, REC, batch_id, 100_000, [("Copper", 100_000)], 0)
    _confirm(app_client, [op], at(minutes=10))
    material_id = material_id_for(op.txid, 0)
    response = app_client.client.get(f"/api/app/materials/{material_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["materialId"] == material_id
    assert body["completion"]["completed"] is False
    assert body["completion"]["remainingGrams"] == 100_000


def test_material_completes_after_processing(app_client, network):
    _register_all(app_client, network)
    _, config = network
    batch_id = _deliver_to_recycler(app_client, network)
    op = process_tx(config, REC, batch_id, 100_000, [("Copper", 100_000)], 0)
    _confirm(app_client, [op], at(minutes=10))
    material_id = material_id_for(op.txid, 0)
    _transfer_material(app_client, network, material_id, 100_000, 12)
    proc = process_tx(config, MP, material_id, 100_000, [("Ingot", 100_000)], 0)
    _confirm(app_client, [proc], at(minutes=20))
    response = app_client.client.get(f"/api/app/materials/{material_id}")
    assert response.status_code == 200
    assert response.json()["completion"]["completed"] is True
    assert response.json()["completion"]["remainingGrams"] == 0


def test_unknown_material_returns_404(app_client):
    response = app_client.client.get("/api/app/materials/nonexistent")
    assert response.status_code == 404


def test_operation_list_and_detail(app_client, network):
    _register_all(app_client, network)
    _, config = network
    batch_id = _deliver_to_recycler(app_client, network)
    op = process_tx(config, REC, batch_id, 100_000, [("Copper", 70_000)], 30_000, method="Shredding")
    _confirm(app_client, [op], at(minutes=10))
    response = app_client.client.get("/api/app/processing")
    assert response.status_code == 200
    operations = response.json()["operations"]
    assert len(operations) == 1
    assert operations[0]["operationId"] == op.txid
    assert operations[0]["inputGrams"] == 100_000
    assert operations[0]["residualGrams"] == 30_000
    assert operations[0]["method"] == "Shredding"

    detail = app_client.client.get(f"/api/app/processing/{op.txid}")
    assert detail.status_code == 200
    assert detail.json()["processor"] == wallet_pub(REC)


def test_unknown_operation_returns_404(app_client):
    response = app_client.client.get("/api/app/processing/nonexistent")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Traceability
# ---------------------------------------------------------------------------


def test_batch_traceability_shows_custody_lineage(app_client, network):
    _register_all(app_client, network)
    _, config = network
    batch_id = _deliver_to_recycler(app_client, network)
    op = process_tx(config, REC, batch_id, 100_000, [("Copper", 100_000)], 0)
    _confirm(app_client, [op], at(minutes=10))
    response = app_client.client.get(f"/api/app/batches/{batch_id}/traceability")
    assert response.status_code == 200
    entries = response.json()["lineage"]
    kinds = [e["kind"] for e in entries]
    assert kinds[0] == "batch"
    assert "transfer" in kinds
    assert len([k for k in kinds if k == "transfer"]) == 3


def test_material_traceability_shows_parent_chain(app_client, network):
    _register_all(app_client, network)
    _, config = network
    batch_id = _deliver_to_recycler(app_client, network)
    op = process_tx(config, REC, batch_id, 100_000, [("Copper", 100_000)], 0)
    _confirm(app_client, [op], at(minutes=10))
    material_id = material_id_for(op.txid, 0)
    response = app_client.client.get(f"/api/app/materials/{material_id}/traceability")
    assert response.status_code == 200
    entries = response.json()["lineage"]
    kinds = [e["kind"] for e in entries]
    assert "batch" in kinds
    assert "processing" in kinds


def test_traceability_includes_corrections(app_client, network):
    _register_all(app_client, network)
    _, config = network
    batch_id = _deliver_to_recycler(app_client, network)
    correction = correction_tx(config, GEN, batch_id, "Weight was recounted")
    _confirm(app_client, [correction], at(minutes=10))
    response = app_client.client.get(f"/api/app/batches/{batch_id}/traceability")
    assert response.status_code == 200
    entries = response.json()["lineage"]
    assert any(e["kind"] == "correction" for e in entries)


def test_traceability_for_unknown_batch_returns_404(app_client):
    response = app_client.client.get("/api/app/batches/unknown/traceability")
    assert response.status_code == 404


def test_traceability_for_unknown_material_returns_404(app_client):
    response = app_client.client.get("/api/app/materials/unknown/traceability")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Transaction status
# ---------------------------------------------------------------------------


def test_transaction_status_confirmed(app_client, network):
    _register_all(app_client, network)
    _, config = network
    batch = batch_tx(config, GEN, 100_000)
    block = _confirm(app_client, [batch], at(minutes=2))
    response = app_client.client.get(f"/api/app/transactions/{batch.txid}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "confirmed"
    assert body["blockHeight"] == block.height


def test_transaction_status_pending(app_client, network):
    _register_all(app_client, network)
    _, config = network
    batch = batch_tx(config, GEN, 100_000)
    _confirm(app_client, [batch], at(minutes=2))
    transfer = request_tx(config, GEN, batch.txid, COL, 40_000)
    app_client.pool.admit(transfer)
    response = app_client.client.get(f"/api/app/transactions/{transfer.txid}")
    assert response.status_code == 200
    assert response.json()["status"] == "pending"


def test_transaction_status_unknown(app_client):
    response = app_client.client.get("/api/app/transactions/nonexistent-txid")
    assert response.status_code == 200
    assert response.json()["status"] == "unknown"


# ---------------------------------------------------------------------------
# Chain status
# ---------------------------------------------------------------------------


def test_chain_status_reflects_current_tip(app_client, network):
    _register_all(app_client, network)
    _, config = network
    batch = batch_tx(config, GEN, 100_000)
    block = _confirm(app_client, [batch], at(minutes=2))
    response = app_client.client.get("/api/app/chain")
    assert response.status_code == 200
    body = response.json()
    assert body["tipHeight"] == block.height
    assert body["tipHash"] == block.block_hash
    assert body["difficulty"] == config.initial_difficulty


# ---------------------------------------------------------------------------
# Reorganization: canonical state is rebuilt
# ---------------------------------------------------------------------------


def test_batch_disappears_after_reorganization(app_client, network):
    _register_all(app_client, network)
    _, config = network
    batch = batch_tx(config, GEN, 100_000)
    batch_block = _confirm(app_client, [batch], at(minutes=2))

    fork_point = app_client.storage.store.blocks_by_hash[batch_block.previous_hash]
    branch_tip = fork_point
    for minute in (2, 3, 4):
        branch_tip = mine(config, branch_tip, [], at(minutes=minute, seconds=1))
        app_client.storage.add_block(branch_tip)

    response = app_client.client.get("/api/app/batches")
    assert response.status_code == 200
    assert response.json() == {"batches": []}


def test_material_disappears_after_reorganization(app_client, network):
    _register_all(app_client, network)
    _, config = network
    batch_id = _deliver_to_recycler(app_client, network)
    op = process_tx(config, REC, batch_id, 100_000, [("Copper", 100_000)], 0)
    op_block = _confirm(app_client, [op], at(minutes=10))

    fork_point = app_client.storage.store.blocks_by_hash[op_block.previous_hash]
    branch_tip = fork_point
    for minute in (11, 12, 13):
        branch_tip = mine(config, branch_tip, [], at(minutes=minute, seconds=1))
        app_client.storage.add_block(branch_tip)

    response = app_client.client.get("/api/app/materials")
    assert response.status_code == 200
    assert response.json() == {"materials": []}


# ---------------------------------------------------------------------------
# Pending vs confirmed distinction in batch completion
# ---------------------------------------------------------------------------


def test_pending_transfer_reflected_in_completion(app_client, network):
    _register_all(app_client, network)
    _, config = network
    batch = batch_tx(config, GEN, 100_000)
    _confirm(app_client, [batch], at(minutes=2))
    request = request_tx(config, GEN, batch.txid, COL, 40_000)
    _confirm(app_client, [request], at(minutes=3))
    response = app_client.client.get(f"/api/app/batches/{batch.txid}")
    assert response.status_code == 200
    completion = response.json()["completion"]
    assert completion["pendingGrams"] == 40_000
    assert completion["remainingGrams"] == 100_000
    assert completion["completed"] is False


# ---------------------------------------------------------------------------
# Write-transaction API (Stage 9.2)
# ---------------------------------------------------------------------------


def _now_str(offset_minutes: int = 0) -> str:
    moment = datetime.now(UTC) + timedelta(minutes=offset_minutes)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _tx_body(transaction) -> dict:
    return {"transaction": transaction.to_dict()}


def _submit(client, transaction):
    return client.post("/api/app/transactions", json=_tx_body(transaction))


def _submit_typed(client, tx_type, transaction):
    return client.post(f"/api/app/transactions/{tx_type}", json=_tx_body(transaction))


def test_generic_submit_accepts_batch_create(app_client_now, network_now):
    _register_all_now(app_client_now, network_now)
    _, config = network_now
    batch = batch_tx(config, GEN, 50_000)
    response = _submit(app_client_now.client, batch)
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "accepted"
    assert body["txid"] == batch.txid


def test_typed_submit_accepts_batch_create(app_client_now, network_now):
    _register_all_now(app_client_now, network_now)
    _, config = network_now
    batch = batch_tx(config, GEN, 50_000)
    response = _submit_typed(app_client_now.client, "batch.create", batch)
    assert response.status_code == 200
    assert response.json()["state"] == "accepted"


def test_typed_submit_rejects_wrong_type(app_client_now, network_now):
    _register_all_now(app_client_now, network_now)
    _, config = network_now
    batch = batch_tx(config, GEN, 50_000)
    response = _submit_typed(app_client_now.client, "transfer.request", batch)
    assert response.status_code == 422
    assert "transfer.request" in response.json()["detail"]


def test_submit_invalid_structure_returns_422(app_client):
    response = app_client.client.post("/api/app/transactions", json={"transaction": {"foo": "bar"}})
    assert response.status_code == 422


def test_submit_missing_transaction_field_returns_422(app_client):
    response = app_client.client.post("/api/app/transactions", json={})
    assert response.status_code == 422


def test_submit_rejected_transaction_returns_422(app_client_now, network_now):
    _, config = network_now
    batch = batch_tx(config, "unknown-wallet", 50_000)
    response = _submit(app_client_now.client, batch)
    assert response.status_code == 422


def test_submit_known_transaction_returns_200(app_client_now, network_now):
    _register_all_now(app_client_now, network_now)
    _, config = network_now
    batch = batch_tx(config, GEN, 50_000)
    first = _submit(app_client_now.client, batch)
    assert first.status_code == 200
    assert first.json()["state"] == "accepted"
    second = _submit(app_client_now.client, batch)
    assert second.status_code == 200
    assert second.json()["state"] == "known"


def test_submit_confirmed_transaction_returns_200(app_client_now, network_now):
    _register_all_now(app_client_now, network_now)
    _, config = network_now
    batch = batch_tx(config, GEN, 50_000)
    _confirm(app_client_now, [batch], _now_str(-25))
    response = _submit(app_client_now.client, batch)
    assert response.status_code == 200
    assert response.json()["state"] == "confirmed"


def test_submit_transfer_request_accepted(app_client_now, network_now):
    _register_all_now(app_client_now, network_now)
    _, config = network_now
    batch = batch_tx(config, GEN, 100_000)
    _confirm(app_client_now, [batch], _now_str(-5))
    request = request_tx(config, GEN, batch.txid, COL, 40_000)
    response = _submit_typed(app_client_now.client, "transfer.request", request)
    assert response.status_code == 200
    assert response.json()["state"] == "accepted"
    assert response.json()["txid"] == request.txid


def test_submit_transfer_accept_accepted(app_client_now, network_now):
    _register_all_now(app_client_now, network_now)
    _, config = network_now
    batch = batch_tx(config, GEN, 100_000)
    _confirm(app_client_now, [batch], _now_str(-10))
    request = request_tx(config, GEN, batch.txid, COL, 40_000)
    _confirm(app_client_now, [request], _now_str(-8))
    accept = accept_tx(config, COL, request.txid, 40_000)
    response = _submit_typed(app_client_now.client, "transfer.accept", accept)
    assert response.status_code == 200
    assert response.json()["state"] == "accepted"


def test_submit_transfer_reject_accepted(app_client_now, network_now):
    _register_all_now(app_client_now, network_now)
    _, config = network_now
    batch = batch_tx(config, GEN, 100_000)
    _confirm(app_client_now, [batch], _now_str(-10))
    request = request_tx(config, GEN, batch.txid, COL, 40_000)
    _confirm(app_client_now, [request], _now_str(-8))
    reject = reject_tx(config, COL, request.txid, "Damaged goods")
    response = _submit_typed(app_client_now.client, "transfer.reject", reject)
    assert response.status_code == 200
    assert response.json()["state"] == "accepted"


def test_submit_transfer_cancel_accepted(app_client_now, network_now):
    _register_all_now(app_client_now, network_now)
    _, config = network_now
    batch = batch_tx(config, GEN, 100_000)
    _confirm(app_client_now, [batch], _now_str(-10))
    request = request_tx(config, GEN, batch.txid, COL, 40_000)
    _confirm(app_client_now, [request], _now_str(-8))
    cancel = cancel_tx(config, GEN, request.txid)
    response = _submit_typed(app_client_now.client, "transfer.cancel", cancel)
    assert response.status_code == 200
    assert response.json()["state"] == "accepted"


def test_submit_processing_record_accepted(app_client_now, network_now):
    _register_all_now(app_client_now, network_now)
    _, config = network_now
    batch_id = _deliver_to_recycler_now(app_client_now, network_now)
    op = process_tx(config, REC, batch_id, 100_000, [("Copper", 100_000)], 0)
    response = _submit_typed(app_client_now.client, "processing.record", op)
    assert response.status_code == 200
    assert response.json()["state"] == "accepted"


def test_submit_correction_accepted(app_client_now, network_now):
    _register_all_now(app_client_now, network_now)
    _, config = network_now
    batch_id = _deliver_to_recycler_now(app_client_now, network_now)
    correction = correction_tx(config, GEN, batch_id, "Weight was recounted")
    response = _submit_typed(app_client_now.client, "record.correct", correction)
    assert response.status_code == 200
    assert response.json()["state"] == "accepted"


def test_submit_processing_rejects_conservation_violation(app_client_now, network_now):
    _register_all_now(app_client_now, network_now)
    _, config = network_now
    batch_id = _deliver_to_recycler_now(app_client_now, network_now)
    op = process_tx(config, REC, batch_id, 100_000, [("Copper", 150_000)], 0)
    response = _submit_typed(app_client_now.client, "processing.record", op)
    assert response.status_code == 422


def test_submit_transfer_rejects_wrong_role(app_client_now, network_now):
    _register_all_now(app_client_now, network_now)
    _, config = network_now
    batch = batch_tx(config, GEN, 100_000)
    _confirm(app_client_now, [batch], _now_str(-5))
    request = request_tx(config, TRA, batch.txid, COL, 40_000)
    response = _submit_typed(app_client_now.client, "transfer.request", request)
    assert response.status_code == 422


def test_submit_corrupted_signature_rejected(app_client_now, network_now):
    _register_all_now(app_client_now, network_now)
    _, config = network_now
    batch = batch_tx(config, GEN, 50_000)
    tampered = copy.deepcopy(batch.to_dict())
    tampered["signature"] = "0" * 128
    response = app_client_now.client.post("/api/app/transactions", json={"transaction": tampered})
    assert response.status_code == 422


def test_submit_tampered_payload_rejected(app_client_now, network_now):
    _register_all_now(app_client_now, network_now)
    _, config = network_now
    batch = batch_tx(config, GEN, 50_000)
    tampered = copy.deepcopy(batch.to_dict())
    tampered["payload"]["quantityGrams"] = 999_999
    response = app_client_now.client.post("/api/app/transactions", json={"transaction": tampered})
    assert response.status_code == 422


def test_submit_then_check_pending_status(app_client_now, network_now):
    _register_all_now(app_client_now, network_now)
    _, config = network_now
    batch = batch_tx(config, GEN, 50_000)
    submit_response = _submit(app_client_now.client, batch)
    assert submit_response.status_code == 200
    assert submit_response.json()["state"] == "accepted"
    status = app_client_now.client.get(f"/api/app/transactions/{batch.txid}")
    assert status.status_code == 200
    assert status.json()["status"] == "pending"


def test_submit_then_confirm_then_check_confirmed(app_client_now, network_now):
    _register_all_now(app_client_now, network_now)
    _, config = network_now
    batch = batch_tx(config, GEN, 50_000)
    _submit(app_client_now.client, batch)
    _confirm(app_client_now, [batch], _now_str(-25))
    status = app_client_now.client.get(f"/api/app/transactions/{batch.txid}")
    assert status.status_code == 200
    assert status.json()["status"] == "confirmed"


def test_full_batch_lifecycle_via_write_api(app_client_now, network_now):
    _register_all_now(app_client_now, network_now)
    _, config = network_now
    batch = batch_tx(config, GEN, 100_000)
    assert _submit(app_client_now.client, batch).status_code == 200
    _confirm(app_client_now, [batch], _now_str(-10))
    request = request_tx(config, GEN, batch.txid, COL, 100_000)
    assert _submit_typed(app_client_now.client, "transfer.request", request).status_code == 200
    _confirm(app_client_now, [request], _now_str(-8))
    accept = accept_tx(config, COL, request.txid, 100_000)
    assert _submit_typed(app_client_now.client, "transfer.accept", accept).status_code == 200
    _confirm(app_client_now, [accept], _now_str(-6))
    detail = app_client_now.client.get(f"/api/app/batches/{batch.txid}")
    assert detail.status_code == 200
    assert detail.json()["completion"]["remainingGrams"] == 100_000


def test_typed_endpoint_unknown_type_returns_405(app_client):
    response = app_client.client.post("/api/app/transactions/nonexistent.type", json={"transaction": {}})
    assert response.status_code == 405


def test_submit_empty_transaction_dict_returns_422(app_client):
    response = app_client.client.post("/api/app/transactions", json={"transaction": {}})
    assert response.status_code == 422


def test_submit_transfer_self_transfer_rejected(app_client_now, network_now):
    _register_all_now(app_client_now, network_now)
    _, config = network_now
    batch = batch_tx(config, GEN, 100_000)
    _confirm(app_client_now, [batch], _now_str(-5))
    request = request_tx(config, GEN, batch.txid, GEN, 40_000)
    response = _submit_typed(app_client_now.client, "transfer.request", request)
    assert response.status_code == 422


def test_submit_transfer_insufficient_quantity_rejected(app_client_now, network_now):
    _register_all_now(app_client_now, network_now)
    _, config = network_now
    batch = batch_tx(config, GEN, 50_000)
    _confirm(app_client_now, [batch], _now_str(-5))
    request = request_tx(config, GEN, batch.txid, COL, 60_000)
    response = _submit_typed(app_client_now.client, "transfer.request", request)
    assert response.status_code == 422


def test_submit_transfer_wrong_receiver_accept_rejected(app_client_now, network_now):
    _register_all_now(app_client_now, network_now)
    _, config = network_now
    batch = batch_tx(config, GEN, 100_000)
    _confirm(app_client_now, [batch], _now_str(-10))
    request = request_tx(config, GEN, batch.txid, COL, 40_000)
    _confirm(app_client_now, [request], _now_str(-8))
    accept = accept_tx(config, TRA, request.txid, 40_000)
    response = _submit_typed(app_client_now.client, "transfer.accept", accept)
    assert response.status_code == 422


def test_submit_material_transfer_accepted(app_client_now, network_now):
    _register_all_now(app_client_now, network_now)
    _, config = network_now
    batch_id = _deliver_to_recycler_now(app_client_now, network_now)
    op = process_tx(config, REC, batch_id, 100_000, [("Copper", 100_000)], 0)
    _confirm(app_client_now, [op], _now_str(-3))
    material_id = material_id_for(op.txid, 0)
    request = request_tx(config, REC, material_id, MP, 100_000)
    response = _submit_typed(app_client_now.client, "transfer.request", request)
    assert response.status_code == 200
    assert response.json()["state"] == "accepted"


def test_submit_material_transfer_unauthorized_sender_rejected(app_client_now, network_now):
    _register_all_now(app_client_now, network_now)
    _, config = network_now
    batch_id = _deliver_to_recycler_now(app_client_now, network_now)
    op = process_tx(config, REC, batch_id, 100_000, [("Copper", 100_000)], 0)
    _confirm(app_client_now, [op], _now_str(-3))
    material_id = material_id_for(op.txid, 0)
    request = request_tx(config, GEN, material_id, MP, 100_000)
    response = _submit_typed(app_client_now.client, "transfer.request", request)
    assert response.status_code == 422


def test_submit_processing_unauthorized_processor_rejected(app_client_now, network_now):
    _register_all_now(app_client_now, network_now)
    _, config = network_now
    batch_id = _deliver_to_recycler_now(app_client_now, network_now)
    op = process_tx(config, GEN, batch_id, 100_000, [("Copper", 100_000)], 0)
    response = _submit_typed(app_client_now.client, "processing.record", op)
    assert response.status_code == 422


def test_submit_processing_multiple_outputs_accepted(app_client_now, network_now):
    _register_all_now(app_client_now, network_now)
    _, config = network_now
    batch_id = _deliver_to_recycler_now(app_client_now, network_now)
    op = process_tx(config, REC, batch_id, 100_000, [("Copper", 60_000), ("Plastic", 30_000)], 10_000)
    response = _submit_typed(app_client_now.client, "processing.record", op)
    assert response.status_code == 200
    assert response.json()["state"] == "accepted"


def test_submit_correction_unauthorized_rejected(app_client_now, network_now):
    _register_all_now(app_client_now, network_now)
    _, config = network_now
    batch_id = _deliver_to_recycler_now(app_client_now, network_now)
    correction = correction_tx(config, COL, batch_id, "I should not do this")
    response = _submit_typed(app_client_now.client, "record.correct", correction)
    assert response.status_code == 422


def test_submit_duplicate_transfer_request_rejected(app_client_now, network_now):
    _register_all_now(app_client_now, network_now)
    _, config = network_now
    batch = batch_tx(config, GEN, 100_000)
    _confirm(app_client_now, [batch], _now_str(-5))
    request = request_tx(config, GEN, batch.txid, COL, 40_000)
    first = _submit_typed(app_client_now.client, "transfer.request", request)
    assert first.status_code == 200
    second = _submit_typed(app_client_now.client, "transfer.request", request)
    assert second.status_code == 200
    assert second.json()["state"] == "known"


def test_submit_suspended_generator_rejected(app_client_now, network_now):
    from business_helpers import suspend_tx
    _register_all_now(app_client_now, network_now)
    _, config = network_now
    suspend = suspend_tx(config, GEN)
    _confirm(app_client_now, [suspend], _now_str(-3))
    batch = batch_tx(config, GEN, 50_000, nonce=2)
    response = _submit(app_client_now.client, batch)
    assert response.status_code == 422


def test_write_api_rejected_transaction_not_in_pool(app_client_now, network_now):
    _register_all_now(app_client_now, network_now)
    _, config = network_now
    batch = batch_tx(config, "unknown-wallet", 50_000)
    _submit(app_client_now.client, batch)
    assert app_client_now.pool.get(batch.txid) is None


def test_write_api_accepted_transaction_in_pool(app_client_now, network_now):
    _register_all_now(app_client_now, network_now)
    _, config = network_now
    batch = batch_tx(config, GEN, 50_000)
    _submit(app_client_now.client, batch)
    assert app_client_now.pool.get(batch.txid) is not None
