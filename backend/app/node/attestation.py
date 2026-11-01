import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed, decode_dss_signature, encode_dss_signature

from app.blockchain.structures import parse_utc_timestamp
from app.config.errors import ConfigurationError
from app.config.shared_network import SharedNetworkConfig, epoch_in_force
from app.crypto.canonical import canonical_bytes
from app.crypto.secp256k1 import domain_hash, parse_compressed_public_key

ATTESTATION_KEY_FILE_NAME = "attestation-key.pem"
ATTESTATION_TAG = "EWASTE-ATTESTATION-V1"
PURPOSE_REGISTRATION = "registration"
PURPOSE_EMAIL_CHANGE = "email-change"
ATTESTATION_PURPOSES = frozenset({PURPOSE_REGISTRATION, PURPOSE_EMAIL_CHANGE})

_BODY_FIELDS = (
    "network_id",
    "purpose",
    "wallet_public_key",
    "role",
    "issuer_node_id",
    "epoch",
    "request_id",
    "nonce",
    "issued_at",
)


class AttestationError(ValueError):
    pass


@dataclass(frozen=True)
class Attestation:
    network_id: str
    purpose: str
    wallet_public_key: str
    role: str
    issuer_node_id: str
    epoch: int
    request_id: str
    nonce: str
    issued_at: str
    signature: str

    def body(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in _BODY_FIELDS}

    def to_dict(self) -> dict[str, Any]:
        return {**self.body(), "signature": self.signature}


def attestation_from_dict(value: object) -> Attestation:
    if not isinstance(value, dict) or set(value) != {*_BODY_FIELDS, "signature"}:
        raise AttestationError("The attestation has an unexpected structure.")
    for name in (*_BODY_FIELDS, "signature"):
        if name != "epoch" and not isinstance(value[name], str):
            raise AttestationError(f"The attestation field '{name}' must be text.")
    epoch = value["epoch"]
    if type(epoch) is not int or epoch < 0:
        raise AttestationError("The attestation epoch must be a whole number of at least 0.")
    return Attestation(**value)


def provision_attestation_key(identity_dir: Path) -> None:
    path = identity_dir / ATTESTATION_KEY_FILE_NAME
    if path.exists():
        raise ConfigurationError("An attestation key already exists for this node and is never replaced.")
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(pem)
        handle.flush()
        os.fsync(handle.fileno())


def load_attestation_key(identity_dir: Path) -> ec.EllipticCurvePrivateKey:
    path = identity_dir / ATTESTATION_KEY_FILE_NAME
    try:
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    except (OSError, ValueError, TypeError) as exc:
        raise ConfigurationError(f"The attestation key at '{path}' could not be read.") from exc
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
        raise ConfigurationError(f"The attestation key at '{path}' must be a P-256 key.")
    return key


def attestation_public_key_hex(key: ec.EllipticCurvePrivateKey) -> str:
    return key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.CompressedPoint).hex()


def require_listed_attestation_key(identity_dir: Path, config: SharedNetworkConfig, node_id: str) -> None:
    key = load_attestation_key(identity_dir)
    listed = any(
        entry.node_id == node_id
        and entry.status == "active"
        and entry.attestation_public_key == attestation_public_key_hex(key)
        for entry in config.trust_epochs[-1].nodes
    )
    if not listed:
        raise ConfigurationError(
            f"The attestation key for node '{node_id}' is not an active entry in the latest trust epoch."
        )


def issue_attestation(
    identity_dir: Path,
    config: SharedNetworkConfig,
    *,
    node_id: str,
    purpose: str,
    wallet_public_key: str,
    role: str,
    request_id: str,
    nonce: str,
    issued_at: str,
) -> Attestation:
    key = load_attestation_key(identity_dir)
    latest = config.trust_epochs[-1]
    fields = {
        "network_id": config.network_id,
        "purpose": purpose,
        "wallet_public_key": wallet_public_key,
        "role": role,
        "issuer_node_id": node_id,
        "epoch": latest.epoch,
        "request_id": request_id,
        "nonce": nonce,
        "issued_at": issued_at,
    }
    _check_fields(fields)
    signature = key.sign(_digest(fields), ec.ECDSA(Prehashed(hashes.SHA256())))
    r, s = decode_dss_signature(signature)
    raw_signature = r.to_bytes(32, "big").hex() + s.to_bytes(32, "big").hex()
    return Attestation(**fields, signature=raw_signature)


def verify_attestation(
    attestation: Attestation,
    *,
    config: SharedNetworkConfig,
    expected_purpose: str,
    chain_height: int,
) -> None:
    if attestation.network_id != config.network_id:
        raise AttestationError("The attestation belongs to a different network.")
    if attestation.purpose != expected_purpose:
        raise AttestationError("The attestation was issued for a different operation.")
    _check_fields(attestation.body())

    if attestation.epoch >= len(config.trust_epochs):
        raise AttestationError("The attestation refers to an unknown trust epoch.")
    named_epoch = config.trust_epochs[attestation.epoch]
    if named_epoch.activation_height > chain_height:
        raise AttestationError("The attestation refers to a trust epoch that is not yet active.")

    issuer_key = _issuer_public_key(attestation, named_epoch.nodes)
    in_force = epoch_in_force(config, chain_height)
    if not any(
        entry.node_id == attestation.issuer_node_id
        and entry.status == "active"
        and entry.attestation_public_key == issuer_key
        for entry in in_force.nodes
    ):
        raise AttestationError("The attestation issuer is not an active attestation authority at this height.")

    signature_bytes = _signature_bytes(attestation.signature)
    r = int.from_bytes(signature_bytes[:32], "big")
    s = int.from_bytes(signature_bytes[32:], "big")
    try:
        public_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), bytes.fromhex(issuer_key))
        public_key.verify(encode_dss_signature(r, s), _digest(attestation.body()), ec.ECDSA(Prehashed(hashes.SHA256())))
    except (InvalidSignature, ValueError) as exc:
        raise AttestationError("The attestation signature is not valid.") from exc


def _issuer_public_key(attestation: Attestation, nodes: tuple) -> str:
    for entry in nodes:
        if entry.node_id == attestation.issuer_node_id and entry.status == "active":
            return entry.attestation_public_key
    raise AttestationError("The attestation issuer is not an active attestation authority in the named epoch.")


def _check_fields(fields: dict[str, Any]) -> None:
    if fields["purpose"] not in ATTESTATION_PURPOSES:
        raise AttestationError("The attestation purpose is not recognised.")
    try:
        parse_compressed_public_key(fields["wallet_public_key"])
    except ValueError as exc:
        raise AttestationError("The attestation wallet key is not a valid public key.") from exc
    try:
        parse_utc_timestamp(fields["issued_at"])
    except ValueError as exc:
        raise AttestationError("The attestation issue time is not a valid UTC timestamp.") from exc
    for name in ("role", "issuer_node_id", "request_id", "nonce", "network_id"):
        if not isinstance(fields[name], str) or not fields[name]:
            raise AttestationError(f"The attestation field '{name}' must be non-empty text.")


def _digest(fields: dict[str, Any]) -> bytes:
    body = {name: fields[name] for name in _BODY_FIELDS}
    return domain_hash(ATTESTATION_TAG, canonical_bytes(body))


def _signature_bytes(signature_hex: str) -> bytes:
    try:
        raw = bytes.fromhex(signature_hex)
    except ValueError as exc:
        raise AttestationError("The attestation signature is not valid hexadecimal.") from exc
    if len(raw) != 64:
        raise AttestationError("The attestation signature has an invalid length.")
    return raw
