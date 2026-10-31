import logging
import os
from collections.abc import Mapping

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.health import router as health_router
from app.config.node_settings import load_node_settings
from app.config.shared_network import load_shared_network_config

logger = logging.getLogger(__name__)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled error while handling %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "An unexpected error occurred on the node."})


def create_app(environ: Mapping[str, str] | None = None) -> FastAPI:
    node_settings = load_node_settings(os.environ if environ is None else environ)
    shared_network = load_shared_network_config(node_settings.network_config_path)

    app = FastAPI(title="E-Waste Traceability Node API")
    app.state.node_settings = node_settings
    app.state.shared_network = shared_network
    app.include_router(health_router)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    return app
