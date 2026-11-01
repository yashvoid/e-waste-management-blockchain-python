import ipaddress
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.crypto.password_verifier import MAX_PASSWORD_LENGTH
from app.node.operator_sessions import (
    SESSION_IDLE_SECONDS,
    InvalidOperatorPassword,
    OperatorNotConfigured,
    SignInLocked,
)
from app.storage.backup import export_backup_from_store, import_backup_to_store
from app.storage.errors import StorageError

LOOPBACK_IPV4 = ipaddress.ip_address("127.0.0.1")
LOOPBACK_IPV6 = ipaddress.ip_address("::1")
MAPPED_LOOPBACK_IPV4 = ipaddress.ip_address("::ffff:127.0.0.1")


class BackupPath(BaseModel):
    path: str


class OperatorCredentials(BaseModel):
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


def require_loopback_client(request: Request) -> None:
    client = request.client
    if client is None or not _is_loopback(client.host):
        raise HTTPException(status_code=403, detail="Node management is available only from this computer.")


def require_operator_session(request: Request, authorization: str | None = Header(default=None)) -> None:
    token = _bearer_token(authorization)
    if token is None or not request.app.state.operator_sessions.is_active(token):
        raise HTTPException(status_code=401, detail="Operator sign-in is required.")


def _is_loopback(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address in (LOOPBACK_IPV4, LOOPBACK_IPV6, MAPPED_LOOPBACK_IPV4)


def _bearer_token(authorization: str | None) -> str | None:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme != "Bearer" or not token.strip():
        return None
    return token.strip()


router = APIRouter(
    prefix="/api/node",
    tags=["node-management"],
    dependencies=[Depends(require_loopback_client), Depends(require_operator_session)],
)
session_router = APIRouter(
    prefix="/api/node",
    tags=["node-management"],
    dependencies=[Depends(require_loopback_client)],
)


def _settings(request: Request):
    return request.app.state.node_settings


def _identity(request: Request):
    identity = getattr(request.app.state, "node_identity", None)
    if identity is None:
        raise HTTPException(status_code=503, detail="Node identity is not available.")
    return identity


def _storage(request: Request):
    storage = getattr(request.app.state, "chain_storage", None)
    if storage is None:
        raise HTTPException(status_code=503, detail="Blockchain storage is not available.")
    return storage


def _config(request: Request):
    return request.app.state.shared_network


def _pool(request: Request):
    relay = getattr(request.app.state, "transaction_relay", None)
    if relay is None:
        raise HTTPException(status_code=503, detail="Transaction pool is not available.")
    return relay.pool


def _mining(request: Request):
    controller = getattr(request.app.state, "mining_controller", None)
    if controller is None:
        raise HTTPException(status_code=503, detail="Mining is not available on this node.")
    return controller


def _synchronizer(request: Request):
    return getattr(request.app.state, "chain_synchronizer", None)


def _monitor(request: Request):
    return getattr(request.app.state, "peer_monitor", None)


@session_router.post("/session")
def sign_in(body: OperatorCredentials, request: Request) -> dict[str, Any]:
    try:
        token = request.app.state.operator_sessions.sign_in(body.password)
    except OperatorNotConfigured as exc:
        raise HTTPException(status_code=503, detail="The operator password has not been set on this node.") from exc
    except InvalidOperatorPassword as exc:
        raise HTTPException(status_code=401, detail="The operator password is incorrect.") from exc
    except SignInLocked as exc:
        raise HTTPException(
            status_code=429,
            detail="Too many failed sign-in attempts. Wait 15 minutes before trying again.",
        ) from exc
    return {"token": token, "idleTimeoutSeconds": SESSION_IDLE_SECONDS}


@session_router.delete("/session", dependencies=[Depends(require_operator_session)])
def sign_out(request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    request.app.state.operator_sessions.sign_out(_bearer_token(authorization))
    return {"signedOut": True}


@router.get("/info")
def node_info(request: Request) -> dict[str, Any]:
    settings = _settings(request)
    identity = _identity(request)
    config = _config(request)
    return {
        "nodeId": identity.node_id,
        "listenHost": settings.listen_host,
        "listenPort": settings.listen_port,
        "peerPort": settings.peer_port,
        "certificateSha256": identity.certificate_sha256,
        "networkId": config.network_id,
        "protocolVersion": config.protocol_version,
        "peers": [
            {"nodeId": p.node_id, "host": p.host, "port": p.port}
            for p in settings.peers
        ],
    }


@router.get("/storage")
def storage_health(request: Request) -> dict[str, Any]:
    storage = _storage(request)
    config = _config(request)
    with storage.lock:
        tip = storage.store.tip
        block_count = len(storage.store.blocks_by_hash)
        canonical_height = tip.height
        return {
            "blockCount": block_count,
            "tipHeight": canonical_height,
            "tipHash": tip.block_hash,
            "dataDir": str(storage.data_dir),
            "locked": False,
        }


@router.get("/pending")
def pending_count(request: Request) -> dict[str, Any]:
    pool = _pool(request)
    return {"pendingCount": pool.count()}


@router.get("/sync")
def sync_status(request: Request) -> dict[str, Any]:
    synchronizer = _synchronizer(request)
    monitor = _monitor(request)
    outcomes: dict[str, Any] = {}
    if synchronizer is not None:
        for node_id, outcome in synchronizer.last_outcomes().items():
            outcomes[node_id] = {
                "state": outcome.state,
                "detail": outcome.detail,
                "blocksReceived": outcome.blocks_received,
                "removedTransactions": outcome.removed_transactions,
                "newlyConfirmedTransactions": outcome.newly_confirmed_transactions,
            }
    return {"lastSyncByPeer": outcomes}


@router.get("/mining")
def mining_status(request: Request) -> dict[str, Any]:
    controller = _mining(request)
    return controller.status()


@router.post("/mining/start")
def start_mining(request: Request) -> dict[str, Any]:
    controller = _mining(request)
    if not controller.start():
        return {"started": False, "detail": "Mining is already running."}
    return {"started": True, "detail": "Mining started."}


@router.post("/mining/stop")
def stop_mining(request: Request) -> dict[str, Any]:
    controller = _mining(request)
    if not controller.stop():
        return {"stopped": False, "detail": "Mining is not running."}
    return {"stopped": True, "detail": "Mining stopped."}


@router.post("/backup/export")
def backup_export(body: BackupPath, request: Request) -> dict[str, Any]:
    storage = _storage(request)
    destination = Path(body.path)
    try:
        count = export_backup_from_store(storage, destination)
    except StorageError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"blocksExported": count}


@router.post("/backup/import")
def backup_import(body: BackupPath, request: Request) -> dict[str, Any]:
    storage = _storage(request)
    source = Path(body.path)
    try:
        result = import_backup_to_store(storage, source)
    except StorageError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "addedBlocks": result.added_blocks,
        "canonicalChanged": result.canonical_changed,
    }
