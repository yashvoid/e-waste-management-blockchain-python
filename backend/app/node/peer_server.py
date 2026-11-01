import threading
import time
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool

from app.config.errors import ConfigurationError
from app.config.shared_network import SharedNetworkConfig, trust_configuration_hash
from app.crypto.strict_json import parse_strict_json_bytes
from app.node.identity import NodeIdentity
from app.node.pending_pool import TRANSACTION_ENVELOPE_ALLOWANCE_BYTES
from app.node.peer_chain import canonical_blocks_after, first_canonical_hash, tip_summary
from app.node.peer_protocol import HASH_PATTERN, LOCATOR_PATTERN, MAX_BLOCKS_PER_REQUEST
from app.node.peer_tls import server_tls_options
from app.node.transaction_relay import TransactionRelay
from app.storage.block_records import decode_transaction_object
from app.storage.chain_storage import ChainStorage
from app.storage.errors import StorageError

_START_TIMEOUT_SECONDS = 10.0
_STOP_TIMEOUT_SECONDS = 10.0


def create_peer_app(
    identity: NodeIdentity,
    shared_config: SharedNetworkConfig,
    storage: ChainStorage,
    relay: TransactionRelay,
) -> FastAPI:
    app = FastAPI(title="E-Waste Traceability Peer Service")
    max_request_bytes = shared_config.max_transaction_payload_bytes + TRANSACTION_ENVELOPE_ALLOWANCE_BYTES

    @app.get("/peer/hello")
    def hello() -> dict[str, str | int]:
        return {
            "nodeId": identity.node_id,
            "networkId": shared_config.network_id,
            "protocolVersion": shared_config.protocol_version,
            "genesisHash": shared_config.genesis_hash,
            "trustConfigHash": trust_configuration_hash(shared_config),
        }

    @app.get("/peer/tip")
    def tip() -> dict[str, str | int]:
        summary = tip_summary(storage)
        return {
            **hello(),
            "tipHash": summary.tip_hash,
            "height": summary.height,
            "cumulativeWork": str(summary.cumulative_work),
        }

    @app.get("/peer/locate")
    def locate(hashes: Annotated[str, Query(pattern=LOCATOR_PATTERN)]) -> dict[str, str | None]:
        return {"hash": first_canonical_hash(storage, hashes.split(","))}

    @app.get("/peer/blocks")
    def blocks(
        after_hash: Annotated[str, Query(alias="afterHash", pattern=HASH_PATTERN)],
        limit: Annotated[int, Query(ge=1, le=MAX_BLOCKS_PER_REQUEST)] = MAX_BLOCKS_PER_REQUEST,
    ) -> dict[str, list[dict]]:
        found = canonical_blocks_after(storage, after_hash, limit)
        return {"blocks": [block.to_dict() for block in found]}

    @app.post("/peer/transactions")
    async def transactions(request: Request) -> dict[str, str]:
        raw = await request.body()
        if len(raw) > max_request_bytes:
            raise HTTPException(status_code=413, detail="The transaction announcement is too large.")
        try:
            body = parse_strict_json_bytes(raw, max_request_bytes)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="The transaction announcement is not valid JSON.") from exc
        if not isinstance(body, dict) or set(body) != {"transaction", "originNodeId"}:
            raise HTTPException(status_code=400, detail="The transaction announcement has an invalid structure.")
        origin = body["originNodeId"]
        if origin is not None and not isinstance(origin, str):
            raise HTTPException(status_code=400, detail="The transaction announcement has an invalid origin.")
        try:
            transaction = decode_transaction_object(body["transaction"])
        except StorageError as exc:
            raise HTTPException(status_code=400, detail="The transaction has an invalid structure.") from exc
        result = await run_in_threadpool(relay.receive, transaction, origin)
        return {"result": result.state, "detail": result.detail, "txid": transaction.txid}

    return app



class PeerListener:
    def __init__(
        self,
        *,
        app: FastAPI,
        host: str,
        port: int,
        identity: NodeIdentity,
        trust_bundle: Path,
    ) -> None:
        self._port = port
        self._server = uvicorn.Server(
            uvicorn.Config(
                app,
                host=host,
                port=port,
                log_level="warning",
                **server_tls_options(identity, trust_bundle),
            )
        )
        self._thread = threading.Thread(target=self._server.run, name="peer-listener", daemon=True)

    def start(self) -> None:
        self._thread.start()
        deadline = time.monotonic() + _START_TIMEOUT_SECONDS
        while not self._server.started:
            if not self._thread.is_alive() or time.monotonic() > deadline:
                raise ConfigurationError(
                    f"The peer service could not start on port {self._port}. Check that the port is free "
                    "and that the peer certificates are valid."
                )
            time.sleep(0.02)

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=_STOP_TIMEOUT_SECONDS)
