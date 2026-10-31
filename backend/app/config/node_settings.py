from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from app.config.errors import ConfigurationError

NODE_ID_ENV = "EWASTE_NODE_ID"
LISTEN_HOST_ENV = "EWASTE_LISTEN_HOST"
LISTEN_PORT_ENV = "EWASTE_LISTEN_PORT"
DATA_DIR_ENV = "EWASTE_DATA_DIR"
NETWORK_CONFIG_ENV = "EWASTE_NETWORK_CONFIG"


@dataclass(frozen=True)
class NodeSettings:
    node_id: str
    listen_host: str
    listen_port: int
    data_dir: Path
    network_config_path: Path


def load_node_settings(environ: Mapping[str, str]) -> NodeSettings:
    listen_port = _parse_port(_required(environ, LISTEN_PORT_ENV))
    return NodeSettings(
        node_id=_required(environ, NODE_ID_ENV),
        listen_host=_required(environ, LISTEN_HOST_ENV),
        listen_port=listen_port,
        data_dir=Path(_required(environ, DATA_DIR_ENV)),
        network_config_path=Path(_required(environ, NETWORK_CONFIG_ENV)),
    )


def _required(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name, "").strip()
    if not value:
        raise ConfigurationError(
            f"The required setting {name} is not set. Add it to this node's private configuration."
        )
    return value


def _parse_port(text: str) -> int:
    try:
        port = int(text)
    except ValueError as exc:
        raise ConfigurationError(f"{LISTEN_PORT_ENV} must be a whole number.") from exc
    if not 1 <= port <= 65535:
        raise ConfigurationError(f"{LISTEN_PORT_ENV} must be between 1 and 65535.")
    return port
