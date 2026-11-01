from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.blockchain.ledger import ChainLedger
from app.blockchain.traceability import (
    batch_status,
    can_view_history,
    lineage,
    material_status,
)
from app.blockchain.business import ACCEPTED, PENDING, EXPIRED, REJECTED, CANCELLED
from app.blockchain.business import (
    BATCH_CREATE_TYPE,
    TRANSFER_ACCEPT_TYPE,
    TRANSFER_CANCEL_TYPE,
    TRANSFER_REJECT_TYPE,
    TRANSFER_REQUEST_TYPE,
)
from app.blockchain.processing import CORRECTION_TYPE, PROCESS_TYPE
from app.crypto.canonical import canonical_bytes
from app.crypto.secp256k1 import domain_hash, parse_compressed_public_key, verify_digest
from app.storage.block_records import decode_transaction_object
from app.storage.errors import StorageError

router = APIRouter(prefix="/api/app", tags=["application"])

VIEW_PROOF_TAG = "EWASTE-VIEW-PROOF-V1"
VIEW_PROOF_MAX_AGE = timedelta(minutes=10)

WRITABLE_TRANSACTION_TYPES = frozenset(
    {
        BATCH_CREATE_TYPE,
        TRANSFER_REQUEST_TYPE,
        TRANSFER_ACCEPT_TYPE,
        TRANSFER_REJECT_TYPE,
        TRANSFER_CANCEL_TYPE,
        PROCESS_TYPE,
        CORRECTION_TYPE,
    }
)


class TransactionSubmission(BaseModel):
    transaction: dict[str, Any]


class ViewProof(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    wallet_public_key: str = Field(alias="walletPublicKey", max_length=66)
    item_id: str = Field(alias="itemId", max_length=128)
    issued_at: str = Field(alias="issuedAt", max_length=20)
    signature: str = Field(max_length=128)


def _verify_view_proof(proof: ViewProof, item_id: str) -> str:
    wallet = proof.wallet_public_key
    try:
        parse_compressed_public_key(wallet)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="The wallet public key is not valid.") from exc
    if proof.item_id != item_id:
        raise HTTPException(status_code=422, detail="The proof does not match the requested item.")
    try:
        issued = datetime.strptime(proof.issued_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="The request time is not valid.") from exc
    age = datetime.now(UTC) - issued
    if age > VIEW_PROOF_MAX_AGE or age < -VIEW_PROOF_MAX_AGE:
        raise HTTPException(status_code=401, detail="The signed request has expired. Try again.")
    digest = domain_hash(
        VIEW_PROOF_TAG,
        canonical_bytes(
            {"purpose": "view-history", "walletPublicKey": wallet, "itemId": item_id, "issuedAt": proof.issued_at}
        ),
    )
    if not verify_digest(wallet, digest, proof.signature):
        raise HTTPException(status_code=401, detail="The wallet signature is not valid.")
    return wallet


def _require_view_access(ledger: ChainLedger, viewer: str, item_id: str) -> None:
    if not can_view_history(ledger, viewer, item_id):
        raise HTTPException(status_code=403, detail="Your wallet does not have access to this item's history.")


def _ledger(request: Request) -> ChainLedger:
    storage = request.app.state.chain_storage
    with storage.lock:
        return ChainLedger.from_blocks(storage.store.canonical_chain, storage.config)


def _storage(request: Request):
    return request.app.state.chain_storage


def _config(request: Request):
    return request.app.state.shared_network


def _grams_to_kg(grams: int) -> float:
    return round(grams / 1000, 3)


def _batch_view(ledger: ChainLedger, batch_id: str) -> dict[str, Any] | None:
    batch = ledger.business.batch(batch_id)
    if batch is None:
        return None
    status = batch_status(ledger, batch_id)
    return {
        "batchId": batch.batch_id,
        "generator": batch.generator,
        "description": batch.description,
        "quantityGrams": batch.quantity_grams,
        "quantityKg": _grams_to_kg(batch.quantity_grams),
        "createdAt": batch.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "completion": _completion_view(status) if status else None,
        "discrepancyGrams": ledger.business.discrepancy(batch_id),
    }


def _material_view(ledger: ChainLedger, material_id: str) -> dict[str, Any] | None:
    material = ledger.processing.material(material_id)
    if material is None:
        return None
    status = material_status(ledger, material_id)
    return {
        "materialId": material.material_id,
        "sourceOperation": material.source_operation,
        "parentItem": material.parent_item,
        "creator": material.creator,
        "description": material.description,
        "quantityGrams": material.quantity_grams,
        "quantityKg": _grams_to_kg(material.quantity_grams),
        "createdAt": material.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "completion": _completion_view(status) if status else None,
    }


def _completion_view(status) -> dict[str, Any]:
    return {
        "completed": status.completed,
        "remainingGrams": status.remaining_grams,
        "remainingKg": _grams_to_kg(status.remaining_grams),
        "processedGrams": status.processed_grams,
        "processedKg": _grams_to_kg(status.processed_grams),
        "residualGrams": status.residual_grams,
        "residualKg": _grams_to_kg(status.residual_grams),
        "discrepancyGrams": status.discrepancy_grams,
        "pendingGrams": status.pending_grams,
        "pendingKg": _grams_to_kg(status.pending_grams),
    }


def _transfer_view(transfer) -> dict[str, Any]:
    return {
        "transferId": transfer.transfer_id,
        "batchId": transfer.batch_id,
        "sender": transfer.sender,
        "receiver": transfer.receiver,
        "declaredGrams": transfer.declared_grams,
        "declaredKg": _grams_to_kg(transfer.declared_grams),
        "status": transfer.status,
        "actualGrams": transfer.actual_grams,
        "actualKg": _grams_to_kg(transfer.actual_grams) if transfer.actual_grams is not None else None,
        "reason": transfer.reason,
        "requestedAt": transfer.requested_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expiresAt": transfer.expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _operation_view(ledger: ChainLedger, operation_id: str) -> dict[str, Any] | None:
    operation = ledger.processing.operation(operation_id)
    if operation is None:
        return None
    return {
        "operationId": operation.operation_id,
        "processor": operation.processor,
        "inputItem": operation.input_item,
        "inputGrams": operation.input_grams,
        "inputKg": _grams_to_kg(operation.input_grams),
        "outputIds": list(operation.output_ids),
        "residualGrams": operation.residual_grams,
        "residualKg": _grams_to_kg(operation.residual_grams),
        "method": operation.method,
        "processedAt": operation.processed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _lineage_view(ledger: ChainLedger, item_id: str) -> list[dict[str, Any]] | None:
    entries = lineage(ledger, item_id)
    if not entries:
        return None
    return [
        {
            "kind": entry.kind,
            "recordId": entry.record_id,
            "participants": list(entry.participants),
            "quantityGrams": entry.quantity_grams,
            "quantityKg": _grams_to_kg(entry.quantity_grams) if entry.quantity_grams is not None else None,
        }
        for entry in entries
    ]


@router.get("/batches")
def list_batches(request: Request) -> dict[str, Any]:
    ledger = _ledger(request)
    batches = ledger.business.batches()
    return {"batches": [_batch_view(ledger, b.batch_id) for b in batches]}


@router.get("/batches/{batch_id}")
def get_batch(batch_id: str, request: Request) -> dict[str, Any]:
    ledger = _ledger(request)
    view = _batch_view(ledger, batch_id)
    if view is None:
        raise HTTPException(status_code=404, detail="This batch does not exist on the accepted chain.")
    return view


@router.post("/batches/{batch_id}/view")
def view_batch(batch_id: str, proof: ViewProof, request: Request) -> dict[str, Any]:
    ledger = _ledger(request)
    view = _batch_view(ledger, batch_id)
    if view is None:
        raise HTTPException(status_code=404, detail="This batch does not exist on the accepted chain.")
    viewer = _verify_view_proof(proof, batch_id)
    _require_view_access(ledger, viewer, batch_id)
    return view


@router.get("/batches/{batch_id}/transfers")
def get_batch_transfers(batch_id: str, request: Request) -> dict[str, Any]:
    ledger = _ledger(request)
    if ledger.business.batch(batch_id) is None:
        raise HTTPException(status_code=404, detail="This batch does not exist on the accepted chain.")
    transfers = [t for t in ledger.business.transfers() if t.batch_id == batch_id]
    return {"batchId": batch_id, "transfers": [_transfer_view(t) for t in transfers]}


@router.post("/batches/{batch_id}/transfers/view")
def view_batch_transfers(batch_id: str, proof: ViewProof, request: Request) -> dict[str, Any]:
    ledger = _ledger(request)
    if ledger.business.batch(batch_id) is None:
        raise HTTPException(status_code=404, detail="This batch does not exist on the accepted chain.")
    viewer = _verify_view_proof(proof, batch_id)
    _require_view_access(ledger, viewer, batch_id)
    transfers = [t for t in ledger.business.transfers() if t.batch_id == batch_id]
    return {"batchId": batch_id, "transfers": [_transfer_view(t) for t in transfers]}


@router.get("/batches/{batch_id}/traceability")
def get_batch_traceability(batch_id: str, request: Request) -> dict[str, Any]:
    ledger = _ledger(request)
    if ledger.business.batch(batch_id) is None:
        raise HTTPException(status_code=404, detail="This batch does not exist on the accepted chain.")
    entries = _lineage_view(ledger, batch_id)
    return {"batchId": batch_id, "lineage": entries or []}


@router.post("/batches/{batch_id}/traceability/view")
def view_batch_traceability(batch_id: str, proof: ViewProof, request: Request) -> dict[str, Any]:
    ledger = _ledger(request)
    if ledger.business.batch(batch_id) is None:
        raise HTTPException(status_code=404, detail="This batch does not exist on the accepted chain.")
    viewer = _verify_view_proof(proof, batch_id)
    _require_view_access(ledger, viewer, batch_id)
    entries = _lineage_view(ledger, batch_id)
    return {"batchId": batch_id, "lineage": entries or []}


@router.get("/materials")
def list_materials(request: Request) -> dict[str, Any]:
    ledger = _ledger(request)
    materials = ledger.processing.materials()
    return {"materials": [_material_view(ledger, m.material_id) for m in materials]}


@router.get("/materials/{material_id}")
def get_material(material_id: str, request: Request) -> dict[str, Any]:
    ledger = _ledger(request)
    view = _material_view(ledger, material_id)
    if view is None:
        raise HTTPException(status_code=404, detail="This recovered material does not exist on the accepted chain.")
    return view


@router.post("/materials/{material_id}/view")
def view_material(material_id: str, proof: ViewProof, request: Request) -> dict[str, Any]:
    ledger = _ledger(request)
    view = _material_view(ledger, material_id)
    if view is None:
        raise HTTPException(status_code=404, detail="This recovered material does not exist on the accepted chain.")
    viewer = _verify_view_proof(proof, material_id)
    _require_view_access(ledger, viewer, material_id)
    return view


@router.get("/materials/{material_id}/traceability")
def get_material_traceability(material_id: str, request: Request) -> dict[str, Any]:
    ledger = _ledger(request)
    if ledger.processing.material(material_id) is None:
        raise HTTPException(status_code=404, detail="This recovered material does not exist on the accepted chain.")
    entries = _lineage_view(ledger, material_id)
    return {"materialId": material_id, "lineage": entries or []}


@router.post("/materials/{material_id}/traceability/view")
def view_material_traceability(material_id: str, proof: ViewProof, request: Request) -> dict[str, Any]:
    ledger = _ledger(request)
    if ledger.processing.material(material_id) is None:
        raise HTTPException(status_code=404, detail="This recovered material does not exist on the accepted chain.")
    viewer = _verify_view_proof(proof, material_id)
    _require_view_access(ledger, viewer, material_id)
    entries = _lineage_view(ledger, material_id)
    return {"materialId": material_id, "lineage": entries or []}


@router.get("/processing")
def list_operations(request: Request) -> dict[str, Any]:
    ledger = _ledger(request)
    operations = ledger.processing.operations()
    return {"operations": [_operation_view(ledger, op.operation_id) for op in operations]}


@router.get("/processing/{operation_id}")
def get_operation(operation_id: str, request: Request) -> dict[str, Any]:
    ledger = _ledger(request)
    view = _operation_view(ledger, operation_id)
    if view is None:
        raise HTTPException(status_code=404, detail="This processing operation does not exist on the accepted chain.")
    return view


@router.get("/transactions/{txid}")
def get_transaction_status(txid: str, request: Request) -> dict[str, Any]:
    storage = _storage(request)
    config = _config(request)
    with storage.lock:
        for block in storage.store.canonical_chain:
            for transaction in block.transactions:
                if transaction.txid == txid:
                    return {
                        "txid": txid,
                        "status": "confirmed",
                        "blockHeight": block.height,
                        "blockHash": block.block_hash,
                    }
        pool = getattr(request.app.state, "transaction_relay", None)
        if pool is not None:
            pending = pool.pool if hasattr(pool, "pool") else pool
            if hasattr(pending, "get") and pending.get(txid) is not None:
                return {"txid": txid, "status": "pending"}
    return {"txid": txid, "status": "unknown"}


@router.get("/chain")
def get_chain_status(request: Request) -> dict[str, Any]:
    storage = _storage(request)
    config = _config(request)
    with storage.lock:
        tip = storage.store.tip
        return {
            "networkId": config.network_id,
            "protocolVersion": config.protocol_version,
            "tipHash": tip.block_hash,
            "tipHeight": tip.height,
            "difficulty": config.initial_difficulty,
        }


@router.get("/peers")
def get_peer_status(request: Request) -> dict[str, Any]:
    monitor = getattr(request.app.state, "peer_monitor", None)
    if monitor is None:
        return {"peers": []}
    snapshots = monitor.snapshot()
    return {
        "peers": [
            {
                "nodeId": peer.node_id,
                "state": peer.state,
                "detail": peer.detail,
                "lastCheckedAt": peer.last_checked_at,
            }
            for peer in snapshots
        ]
    }


# ---------------------------------------------------------------------------
# Write-transaction API (Stage 9.2)
# ---------------------------------------------------------------------------


def _relay(request: Request):
    relay = getattr(request.app.state, "transaction_relay", None)
    if relay is None:
        raise HTTPException(status_code=503, detail="Transaction submission is not available on this node.")
    return relay


def _submit(body: TransactionSubmission, request: Request, expected_type: str | None = None) -> dict[str, str]:
    try:
        transaction = decode_transaction_object(body.transaction)
    except StorageError as exc:
        raise HTTPException(status_code=422, detail="The transaction has an invalid structure.") from exc
    if expected_type is not None and transaction.tx_type != expected_type:
        raise HTTPException(
            status_code=422,
            detail=f"The transaction type must be {expected_type} for this endpoint.",
        )
    result = _relay(request).submit_local(transaction)
    if result.state == "rejected":
        raise HTTPException(status_code=422, detail=result.detail)
    if result.state == "unavailable":
        raise HTTPException(status_code=503, detail=result.detail)
    return {"state": result.state, "detail": result.detail, "txid": transaction.txid}


@router.post("/transactions")
def submit_transaction(body: TransactionSubmission, request: Request) -> dict[str, str]:
    return _submit(body, request, expected_type=None)


@router.post("/transactions/batch.create")
def submit_batch_create(body: TransactionSubmission, request: Request) -> dict[str, str]:
    return _submit(body, request, expected_type=BATCH_CREATE_TYPE)


@router.post("/transactions/transfer.request")
def submit_transfer_request(body: TransactionSubmission, request: Request) -> dict[str, str]:
    return _submit(body, request, expected_type=TRANSFER_REQUEST_TYPE)


@router.post("/transactions/transfer.accept")
def submit_transfer_accept(body: TransactionSubmission, request: Request) -> dict[str, str]:
    return _submit(body, request, expected_type=TRANSFER_ACCEPT_TYPE)


@router.post("/transactions/transfer.reject")
def submit_transfer_reject(body: TransactionSubmission, request: Request) -> dict[str, str]:
    return _submit(body, request, expected_type=TRANSFER_REJECT_TYPE)


@router.post("/transactions/transfer.cancel")
def submit_transfer_cancel(body: TransactionSubmission, request: Request) -> dict[str, str]:
    return _submit(body, request, expected_type=TRANSFER_CANCEL_TYPE)


@router.post("/transactions/processing.record")
def submit_processing_record(body: TransactionSubmission, request: Request) -> dict[str, str]:
    return _submit(body, request, expected_type=PROCESS_TYPE)


@router.post("/transactions/record.correct")
def submit_correction(body: TransactionSubmission, request: Request) -> dict[str, str]:
    return _submit(body, request, expected_type=CORRECTION_TYPE)
