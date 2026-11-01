import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.blockchain.structures import MAX_DIFFICULTY, MIN_DIFFICULTY, parse_utc_timestamp
from app.config.errors import ConfigurationError
from app.config.node_id import is_valid_node_id
from app.crypto.canonical import MAX_SAFE_INTEGER, canonical_bytes
from app.crypto.hexutil import hex_to_bytes
from app.crypto.secp256k1 import domain_hash

MAX_TRANSACTIONS_PER_BLOCK = 100
MAX_BLOCK_SIZE_BYTES = 1024 * 1024
MAX_TRANSACTION_PAYLOAD_BYTES = 16 * 1024

_FINGERPRINT_PATTERN = re.compile(r"[0-9a-f]{64}")
_ATTESTATION_KEY_PATTERN = re.compile(r"0[23][0-9a-f]{64}")
NODE_STATUSES = frozenset({"active", "retired", "revoked"})

_REQUIRED_KEYS = frozenset(
    {
        "network_id",
        "protocol_version",
        "genesis_timestamp",
        "genesis_nonce",
        "genesis_hash",
        "initial_difficulty",
        "max_transactions_per_block",
        "max_block_size_bytes",
        "max_transaction_payload_bytes",
        "trust_epochs",
    }
)


@dataclass(frozen=True)
class TrustedNode:
    node_id: str
    tls_certificate_sha256: str
    attestation_public_key: str
    status: str


@dataclass(frozen=True)
class TrustEpoch:
    epoch: int
    activation_height: int
    nodes: tuple[TrustedNode, ...]


@dataclass(frozen=True)
class SharedNetworkConfig:
    network_id: str
    protocol_version: int
    genesis_timestamp: str
    genesis_nonce: int
    genesis_hash: str
    initial_difficulty: int
    max_transactions_per_block: int
    max_block_size_bytes: int
    max_transaction_payload_bytes: int
    trust_epochs: tuple[TrustEpoch, ...]


def epoch_in_force(config: SharedNetworkConfig, height: int) -> TrustEpoch:
    in_force = config.trust_epochs[0]
    for epoch in config.trust_epochs:
        if epoch.activation_height <= height:
            in_force = epoch
    return in_force


TRUST_CONFIGURATION_TAG = "EWASTE-TRUST-CONFIGURATION-V1"


def trust_configuration_hash(config: SharedNetworkConfig) -> str:
    epochs = [
        {
            "epoch": epoch.epoch,
            "activationHeight": epoch.activation_height,
            "nodes": [
                {
                    "nodeId": node.node_id,
                    "tlsCertificateSha256": node.tls_certificate_sha256,
                    "attestationPublicKey": node.attestation_public_key,
                    "status": node.status,
                }
                for node in epoch.nodes
            ],
        }
        for epoch in config.trust_epochs
    ]
    return domain_hash(TRUST_CONFIGURATION_TAG, canonical_bytes(epochs)).hex()


def load_shared_network_config(path: Path) -> SharedNetworkConfig:
    if not path.is_file():
        raise ConfigurationError(f"The shared network configuration file was not found at '{path}'.")

    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigurationError(f"The shared network configuration at '{path}' could not be read.") from exc
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"The shared network configuration at '{path}' is not valid JSON.") from exc

    if not isinstance(raw, dict):
        raise ConfigurationError("The shared network configuration must be a JSON object.")

    unsupported = sorted(set(raw) - _REQUIRED_KEYS)
    if unsupported:
        raise ConfigurationError(
            "The shared network configuration contains settings that are not part of the shared "
            f"configuration: {', '.join(unsupported)}. Node-specific settings belong in the private node configuration."
        )

    missing = sorted(_REQUIRED_KEYS - set(raw))
    if missing:
        raise ConfigurationError(f"The shared network configuration is missing: {', '.join(missing)}.")

    network_id = raw["network_id"]
    if not isinstance(network_id, str) or not network_id.strip():
        raise ConfigurationError("The shared network setting 'network_id' must be a non-empty text value.")

    protocol_version = raw["protocol_version"]
    if isinstance(protocol_version, bool) or not isinstance(protocol_version, int) or protocol_version < 1:
        raise ConfigurationError("The shared network setting 'protocol_version' must be a whole number of at least 1.")

    genesis_timestamp = raw["genesis_timestamp"]
    try:
        parse_utc_timestamp(genesis_timestamp)
    except ValueError as exc:
        raise ConfigurationError(
            "The shared network setting 'genesis_timestamp' must be a UTC ISO 8601 time ending in Z."
        ) from exc

    genesis_nonce = _whole_number(raw, "genesis_nonce", minimum=0, maximum=MAX_SAFE_INTEGER)
    initial_difficulty = _whole_number(raw, "initial_difficulty", minimum=MIN_DIFFICULTY, maximum=MAX_DIFFICULTY)
    max_transactions_per_block = _whole_number(
        raw, "max_transactions_per_block", minimum=1, maximum=MAX_TRANSACTIONS_PER_BLOCK
    )
    max_block_size_bytes = _whole_number(raw, "max_block_size_bytes", minimum=1, maximum=MAX_BLOCK_SIZE_BYTES)
    max_transaction_payload_bytes = _whole_number(
        raw, "max_transaction_payload_bytes", minimum=1, maximum=MAX_TRANSACTION_PAYLOAD_BYTES
    )

    genesis_hash = raw["genesis_hash"]
    try:
        hex_to_bytes(genesis_hash, 32)
    except ValueError as exc:
        raise ConfigurationError(
            "The shared network setting 'genesis_hash' must be 64 lowercase hexadecimal characters."
        ) from exc

    trust_epochs = _trust_epochs(raw["trust_epochs"])

    return SharedNetworkConfig(
        network_id=network_id.strip(),
        protocol_version=protocol_version,
        genesis_timestamp=genesis_timestamp,
        genesis_nonce=genesis_nonce,
        genesis_hash=genesis_hash,
        initial_difficulty=initial_difficulty,
        max_transactions_per_block=max_transactions_per_block,
        max_block_size_bytes=max_block_size_bytes,
        max_transaction_payload_bytes=max_transaction_payload_bytes,
        trust_epochs=trust_epochs,
    )


def _trust_epochs(value: Any) -> tuple[TrustEpoch, ...]:
    if not isinstance(value, list) or not value:
        raise ConfigurationError("The shared network setting 'trust_epochs' must be a non-empty list.")

    epochs: list[TrustEpoch] = []
    for position, entry in enumerate(value):
        if not isinstance(entry, dict) or set(entry) != {"epoch", "activation_height", "nodes"}:
            raise ConfigurationError(
                "Each trust epoch must contain exactly 'epoch', 'activation_height' and 'nodes'."
            )
        epoch_number = _non_negative_int(entry["epoch"], "epoch")
        activation_height = _non_negative_int(entry["activation_height"], "activation_height")
        if epoch_number != position:
            raise ConfigurationError("Trust epoch numbers must start at 0 and increase by 1.")
        if position == 0 and activation_height != 0:
            raise ConfigurationError("The first trust epoch must activate at block height 0.")
        if position > 0 and activation_height <= epochs[-1].activation_height:
            raise ConfigurationError("Trust epoch activation heights must strictly increase.")
        epochs.append(TrustEpoch(epoch=epoch_number, activation_height=activation_height, nodes=_epoch_nodes(entry["nodes"])))

    _check_revocations_stay_revoked(epochs)
    return tuple(epochs)


def _epoch_nodes(value: Any) -> tuple[TrustedNode, ...]:
    if not isinstance(value, list) or not value:
        raise ConfigurationError("Each trust epoch must list at least one node.")

    nodes: list[TrustedNode] = []
    for entry in value:
        if not isinstance(entry, dict) or set(entry) != {
            "node_id",
            "tls_certificate_sha256",
            "attestation_public_key",
            "status",
        }:
            raise ConfigurationError(
                "Each trust epoch node must contain exactly 'node_id', 'tls_certificate_sha256', "
                "'attestation_public_key' and 'status'."
            )
        node_id = entry["node_id"]
        fingerprint = entry["tls_certificate_sha256"]
        attestation_key = entry["attestation_public_key"]
        status = entry["status"]
        if not isinstance(node_id, str) or not is_valid_node_id(node_id):
            raise ConfigurationError("Each trusted node ID must use 1 to 63 lowercase letters, digits or hyphens.")
        if not isinstance(fingerprint, str) or _FINGERPRINT_PATTERN.fullmatch(fingerprint) is None:
            raise ConfigurationError("Each TLS certificate fingerprint must be 64 lowercase hexadecimal characters.")
        if not isinstance(attestation_key, str) or _ATTESTATION_KEY_PATTERN.fullmatch(attestation_key) is None:
            raise ConfigurationError("Each attestation public key must be a compressed P-256 key in hexadecimal.")
        if status not in NODE_STATUSES:
            raise ConfigurationError("Each trusted node status must be 'active', 'retired' or 'revoked'.")
        nodes.append(
            TrustedNode(
                node_id=node_id,
                tls_certificate_sha256=fingerprint,
                attestation_public_key=attestation_key,
                status=status,
            )
        )

    current = [node.node_id for node in nodes if node.status != "retired"]
    if len(set(current)) != len(current):
        raise ConfigurationError("Each node ID may appear only once as active or revoked in a trust epoch.")
    for node in nodes:
        if node.status == "retired" and not any(
            other.node_id == node.node_id and other.status == "active" for other in nodes
        ):
            raise ConfigurationError(
                f"A retired certificate for node '{node.node_id}' must be listed alongside its active replacement."
            )
    if len({node.tls_certificate_sha256 for node in nodes}) != len(nodes):
        raise ConfigurationError("Each TLS certificate fingerprint may appear only once in a trust epoch.")
    if len({node.attestation_public_key for node in nodes}) != len(nodes):
        raise ConfigurationError("Each attestation public key may appear only once in a trust epoch.")
    return tuple(nodes)


def _check_revocations_stay_revoked(epochs: list[TrustEpoch]) -> None:
    revoked: set[str] = set()
    for epoch in epochs:
        for node in epoch.nodes:
            if node.node_id in revoked and node.status == "active":
                raise ConfigurationError(
                    f"Node '{node.node_id}' was revoked in an earlier trust epoch and cannot become active again."
                )
        revoked.update(node.node_id for node in epoch.nodes if node.status == "revoked")


def _non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ConfigurationError(f"The trust epoch setting '{name}' must be a whole number of at least 0.")
    return value


def _whole_number(raw: dict[str, Any], key: str, *, minimum: int, maximum: int) -> int:
    value = raw[key]
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ConfigurationError(
            f"The shared network setting '{key}' must be a whole number from {minimum} to {maximum}."
        )
    return value
