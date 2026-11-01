import asyncio
import logging
import os
import smtplib
from collections.abc import AsyncIterator, Mapping
from contextlib import ExitStack, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.health import router as health_router
from app.api.participants import router as participants_router
from app.api.application import router as application_router
from app.api.node_management import router as node_management_router
from app.api.node_management import session_router as node_session_router
from app.config.errors import ConfigurationError
from app.config.node_settings import PeerAddress, load_node_settings
from app.config.shared_network import load_shared_network_config
from app.node.attestation import require_listed_attestation_key
from app.node.chain_sync import ChainSynchronizer
from app.node.contact_store import MASTER_KEY_FILE_NAME, ContactStore, initialize_contact_store
from app.node.email_delivery import SmtpSettings, load_smtp_settings
from app.node.identity import load_node_identity
from app.node.otp_service import OtpService
from app.node.peer_monitor import PeerMonitor, PeerTiming
from app.node.peer_server import PeerListener, create_peer_app
from app.node.peer_tls import client_ssl_context
from app.node.peer_trust import (
    accepted_certificate_paths,
    require_listed_identity,
    trusted_peer_certificates,
    write_trust_bundle,
)
from app.node.mining_controller import MiningController
from app.node.operator_sessions import OperatorSessions
from app.node.pending_pool import PendingTransactionPool
from app.node.transaction_relay import TransactionRelay
from app.storage.chain_storage import open_chain_storage

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = app.state.node_settings
    shared_config = app.state.shared_network
    identity = load_node_identity(settings.identity_dir)
    app.state.node_identity = identity
    require_listed_identity(identity, shared_config)
    require_listed_attestation_key(settings.identity_dir, shared_config, identity.node_id)
    peer_certificates = trusted_peer_certificates(settings.identity_dir, shared_config, identity.node_id)
    contexts = {node_id: client_ssl_context(identity, path) for node_id, path in peer_certificates.items()}
    timing = PeerTiming()

    with open_chain_storage(settings.data_dir, shared_config) as chain_storage, ExitStack() as services:
        app.state.chain_storage = chain_storage
        app.state.otp_service = OtpService(_ensure_directory(settings.data_dir / "participants"))
        contacts_dir = _ensure_directory(settings.data_dir / "contacts")
        if not (contacts_dir / MASTER_KEY_FILE_NAME).exists():
            initialize_contact_store(contacts_dir)
        app.state.contact_store = ContactStore(contacts_dir)
        pool = PendingTransactionPool(chain_storage)
        relay = TransactionRelay(
            node_id=identity.node_id,
            pool=pool,
            peers=settings.peers,
            contexts=contexts,
            timeout_seconds=timing.request_timeout_seconds,
        )
        services.callback(relay.close)
        app.state.transaction_relay = relay

        mining_controller = MiningController(storage=chain_storage, config=shared_config, pool=pool)
        app.state.mining_controller = mining_controller

        if peer_certificates:
            listener = PeerListener(
                app=create_peer_app(identity, shared_config, chain_storage, relay),
                host=settings.listen_host,
                port=settings.peer_port,
                identity=identity,
                trust_bundle=write_trust_bundle(
                    settings.identity_dir,
                    accepted_certificate_paths(settings.identity_dir, shared_config, identity.node_id),
                ),
            )
            listener.start()
            services.callback(listener.stop)

        synchronizer = ChainSynchronizer(
            chain_storage=chain_storage,
            shared_config=shared_config,
            contexts=contexts,
            timing=timing,
            pool=pool,
        )
        app.state.chain_synchronizer = synchronizer
        monitor = PeerMonitor(
            identity=identity,
            shared_config=shared_config,
            peers=settings.peers,
            trusted_certificates=peer_certificates,
            on_connected=_on_connected(synchronizer, relay),
        )
        app.state.peer_monitor = monitor
        monitor_task = asyncio.create_task(monitor.run())
        try:
            yield
        finally:
            mining_controller.stop()
            monitor_task.cancel()
            await asyncio.gather(monitor_task, return_exceptions=True)
            await asyncio.to_thread(synchronizer.close)


def _ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _on_connected(synchronizer: ChainSynchronizer, relay: TransactionRelay):
    async def handle(peer: PeerAddress) -> object:
        outcome = await synchronizer.sync_peer(peer)
        relay.send_pending_to(peer)
        return outcome

    return handle


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled error while handling %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "An unexpected error occurred on the node."})


def _optional_smtp_settings(environ: Mapping[str, str]) -> SmtpSettings | None:
    try:
        return load_smtp_settings(environ)
    except ConfigurationError as exc:
        logger.warning("Verification email is disabled on this node: %s", exc)
        return None


def create_app(environ: Mapping[str, str] | None = None) -> FastAPI:
    node_settings = load_node_settings(os.environ if environ is None else environ)
    shared_network = load_shared_network_config(node_settings.network_config_path)

    app = FastAPI(title="E-Waste Traceability Node API", lifespan=lifespan)
    app.state.node_settings = node_settings
    app.state.shared_network = shared_network
    app.state.smtp_settings = _optional_smtp_settings(os.environ if environ is None else environ)
    app.state.smtp_factory = smtplib.SMTP
    app.state.operator_sessions = OperatorSessions(node_settings.operator_verifier)
    app.include_router(health_router)
    app.include_router(participants_router)
    app.include_router(application_router)
    app.include_router(node_session_router)
    app.include_router(node_management_router)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    return app
