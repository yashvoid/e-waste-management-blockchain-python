import ssl
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from app.blockchain.structures import Block
from app.config.node_settings import PeerAddress
from app.config.shared_network import SharedNetworkConfig, trust_configuration_hash
from app.crypto.strict_json import parse_strict_json_bytes
from app.node.peer_protocol import MAX_JSON_RESPONSE_BYTES, WORK_PATTERN
from app.storage.block_records import decode_block_object
from app.storage.errors import StorageError


class PeerUnavailableError(Exception):
    pass


class PeerRejectedError(Exception):
    pass


@dataclass(frozen=True)
class PeerHello:
    node_id: str
    network_id: str
    protocol_version: int
    genesis_hash: str
    trust_config_hash: str


@dataclass(frozen=True)
class PeerTip:
    hello: PeerHello
    tip_hash: str
    height: int
    cumulative_work: int


_HELLO_KEYS = frozenset({"nodeId", "networkId", "protocolVersion", "genesisHash", "trustConfigHash"})
_TIP_KEYS = _HELLO_KEYS | {"tipHash", "height", "cumulativeWork"}
_UNEXPECTED = "The peer answered with an unexpected response."


async def fetch_peer_hello(address: PeerAddress, context: ssl.SSLContext, timeout_seconds: float) -> PeerHello:
    body = await _get_json(address, context, timeout_seconds, "/peer/hello", None, MAX_JSON_RESPONSE_BYTES)
    if not isinstance(body, dict) or set(body) != _HELLO_KEYS:
        raise PeerRejectedError(_UNEXPECTED)
    return _parse_hello(body)


async def fetch_peer_tip(address: PeerAddress, context: ssl.SSLContext, timeout_seconds: float) -> PeerTip:
    body = await _get_json(address, context, timeout_seconds, "/peer/tip", None, MAX_JSON_RESPONSE_BYTES)
    if not isinstance(body, dict) or set(body) != _TIP_KEYS:
        raise PeerRejectedError(_UNEXPECTED)
    height = body["height"]
    work = body["cumulativeWork"]
    if not _is_hash(body["tipHash"]) or not _is_count(height) or not isinstance(work, str):
        raise PeerRejectedError(_UNEXPECTED)
    if WORK_PATTERN.fullmatch(work) is None:
        raise PeerRejectedError(_UNEXPECTED)
    hello = _parse_hello({key: body[key] for key in _HELLO_KEYS})
    return PeerTip(hello=hello, tip_hash=body["tipHash"], height=height, cumulative_work=int(work))


async def fetch_common_block(
    address: PeerAddress,
    context: ssl.SSLContext,
    timeout_seconds: float,
    locator: Sequence[str],
) -> str | None:
    params = {"hashes": ",".join(locator)}
    body = await _get_json(address, context, timeout_seconds, "/peer/locate", params, MAX_JSON_RESPONSE_BYTES)
    if not isinstance(body, dict) or set(body) != {"hash"}:
        raise PeerRejectedError(_UNEXPECTED)
    found = body["hash"]
    if found is None:
        return None
    if not _is_hash(found):
        raise PeerRejectedError(_UNEXPECTED)
    return found


async def fetch_blocks_after(
    address: PeerAddress,
    context: ssl.SSLContext,
    timeout_seconds: float,
    after_hash: str,
    limit: int,
    max_bytes: int,
) -> list[Block]:
    params = {"afterHash": after_hash, "limit": str(limit)}
    body = await _get_json(address, context, timeout_seconds, "/peer/blocks", params, max_bytes)
    if not isinstance(body, dict) or set(body) != {"blocks"} or not isinstance(body["blocks"], list):
        raise PeerRejectedError(_UNEXPECTED)
    if len(body["blocks"]) > limit:
        raise PeerRejectedError(_UNEXPECTED)
    try:
        return [decode_block_object(item) for item in body["blocks"]]
    except StorageError as exc:
        raise PeerRejectedError(_UNEXPECTED) from exc


def incompatibility(hello: PeerHello, expected_node_id: str, shared_config: SharedNetworkConfig) -> str | None:
    if hello.node_id != expected_node_id:
        return "The peer identifies itself as a different node."
    if hello.network_id != shared_config.network_id:
        return "The peer is on a different network ID."
    if hello.protocol_version != shared_config.protocol_version:
        return "The peer uses a different protocol version."
    if hello.genesis_hash != shared_config.genesis_hash:
        return "The peer has a different genesis hash."
    if hello.trust_config_hash != trust_configuration_hash(shared_config):
        return "The peer has a different trust configuration. Both nodes must use the same shared network configuration."
    return None


async def _get_json(
    address: PeerAddress,
    context: ssl.SSLContext,
    timeout_seconds: float,
    path: str,
    params: Mapping[str, str] | None,
    max_bytes: int,
) -> Any:
    url = f"https://{address.host}:{address.port}{path}"
    try:
        async with httpx.AsyncClient(verify=context, timeout=timeout_seconds) as client:
            async with client.stream("GET", url, params=params) as response:
                if response.status_code != 200:
                    raise PeerRejectedError(_UNEXPECTED)
                try:
                    raw = await _read_limited(response, max_bytes)
                except httpx.TransportError as exc:
                    raise PeerUnavailableError("The connection to the peer was interrupted.") from exc
    except httpx.TimeoutException as exc:
        raise PeerUnavailableError("The peer did not respond in time.") from exc
    except httpx.ConnectError as exc:
        if _caused_by_tls_failure(exc):
            raise PeerRejectedError("The secure connection was refused by the peer.") from exc
        raise PeerUnavailableError("The peer could not be reached.") from exc
    except httpx.TransportError as exc:
        raise PeerRejectedError(
            "The peer closed the secure connection before answering. It may not trust this node's certificate."
        ) from exc
    except httpx.HTTPError as exc:
        raise PeerUnavailableError("The peer could not be reached.") from exc

    try:
        return parse_strict_json_bytes(raw, max_bytes)
    except ValueError as exc:
        raise PeerRejectedError(_UNEXPECTED) from exc


async def _read_limited(response: httpx.Response, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > max_bytes:
            raise PeerRejectedError("The peer sent more data than allowed.")
        chunks.append(chunk)
    return b"".join(chunks)


def _caused_by_tls_failure(exc: BaseException) -> bool:
    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, ssl.SSLError):
            return True
        current = current.__cause__ or current.__context__
    return False


def _is_hash(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)


def _is_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _parse_hello(body: dict[str, Any]) -> PeerHello:
    protocol_version = body["protocolVersion"]
    if isinstance(protocol_version, bool) or not isinstance(protocol_version, int):
        raise PeerRejectedError(_UNEXPECTED)
    if not all(isinstance(body[key], str) for key in ("nodeId", "networkId", "genesisHash", "trustConfigHash")):
        raise PeerRejectedError(_UNEXPECTED)
    return PeerHello(
        node_id=body["nodeId"],
        network_id=body["networkId"],
        protocol_version=protocol_version,
        genesis_hash=body["genesisHash"],
        trust_config_hash=body["trustConfigHash"],
    )
