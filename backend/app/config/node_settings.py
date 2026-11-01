from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from app.config.errors import ConfigurationError
from app.config.node_id import is_valid_node_id
from app.crypto.password_verifier import validate_verifier

NODE_ID_ENV = "EWASTE_NODE_ID"
LISTEN_HOST_ENV = "EWASTE_LISTEN_HOST"
LISTEN_PORT_ENV = "EWASTE_LISTEN_PORT"
PEER_PORT_ENV = "EWASTE_PEER_PORT"
DATA_DIR_ENV = "EWASTE_DATA_DIR"
IDENTITY_DIR_ENV = "EWASTE_IDENTITY_DIR"
NETWORK_CONFIG_ENV = "EWASTE_NETWORK_CONFIG"
PEERS_ENV = "EWASTE_PEERS"
OPERATOR_VERIFIER_ENV = "EWASTE_OPERATOR_PASSWORD_VERIFIER"


@dataclass(frozen=True)
class PeerAddress:
    node_id: str
    host: str
    port: int


@dataclass(frozen=True)
class NodeSettings:
    node_id: str
    listen_host: str
    listen_port: int
    peer_port: int
    data_dir: Path
    identity_dir: Path
    network_config_path: Path
    peers: tuple[PeerAddress, ...]
    operator_verifier: str | None = None


def load_node_settings(environ: Mapping[str, str]) -> NodeSettings:
    node_id = _required(environ, NODE_ID_ENV)
    if not is_valid_node_id(node_id):
        raise ConfigurationError(
            f"{NODE_ID_ENV} must use 1 to 63 lowercase letters, digits or hyphens."
        )
    return NodeSettings(
        node_id=node_id,
        listen_host=_required(environ, LISTEN_HOST_ENV),
        listen_port=_parse_port(_required(environ, LISTEN_PORT_ENV), LISTEN_PORT_ENV),
        peer_port=_parse_port(_required(environ, PEER_PORT_ENV), PEER_PORT_ENV),
        data_dir=Path(_required(environ, DATA_DIR_ENV)),
        identity_dir=Path(_required(environ, IDENTITY_DIR_ENV)),
        network_config_path=Path(_required(environ, NETWORK_CONFIG_ENV)),
        peers=_parse_peers(environ.get(PEERS_ENV, ""), own_node_id=node_id),
        operator_verifier=_optional_operator_verifier(environ),
    )


def _optional_operator_verifier(environ: Mapping[str, str]) -> str | None:
    value = environ.get(OPERATOR_VERIFIER_ENV, "").strip()
    if not value:
        return None
    try:
        validate_verifier(value)
    except ValueError as exc:
        raise ConfigurationError(
            f"{OPERATOR_VERIFIER_ENV} is not valid. Create it with the set-operator-password provisioning command."
        ) from exc
    return value


def _required(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name, "").strip()
    if not value:
        raise ConfigurationError(
            f"The required setting {name} is not set. Add it to this node's private configuration."
        )
    return value


def _parse_port(text: str, name: str) -> int:
    try:
        port = int(text)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a whole number.") from exc
    if not 1 <= port <= 65535:
        raise ConfigurationError(f"{name} must be between 1 and 65535.")
    return port


def _parse_peers(text: str, *, own_node_id: str) -> tuple[PeerAddress, ...]:
    peers: list[PeerAddress] = []
    for entry in (part.strip() for part in text.split(",")):
        if not entry:
            continue
        node_id, separator, address = entry.partition("@")
        host, colon, port_text = address.rpartition(":")
        if not separator or not colon or not host or not is_valid_node_id(node_id):
            raise ConfigurationError(
                f"{PEERS_ENV} entries must look like node-id@host:port, separated by commas."
            )
        if node_id == own_node_id:
            raise ConfigurationError(f"{PEERS_ENV} must not list this node itself.")
        peers.append(PeerAddress(node_id=node_id, host=host, port=_parse_port(port_text, PEERS_ENV)))

    if len({peer.node_id for peer in peers}) != len(peers):
        raise ConfigurationError(f"{PEERS_ENV} must not list the same node twice.")
    return tuple(peers)
