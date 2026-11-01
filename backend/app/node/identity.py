import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from app.config.errors import ConfigurationError
from app.config.node_id import is_valid_node_id
from app.node.attestation import provision_attestation_key

IDENTITY_FILE_NAME = "identity.json"
KEY_FILE_NAME = "node-key.pem"
CERTIFICATE_FILE_NAME = "node-certificate.pem"
CERTIFICATE_VALID_DAYS = 3650


@dataclass(frozen=True)
class NodeIdentity:
    node_id: str
    certificate_path: Path
    key_path: Path
    certificate_sha256: str


def certificate_fingerprint(certificate: x509.Certificate) -> str:
    return certificate.fingerprint(hashes.SHA256()).hex()


def load_certificate_file(path: Path) -> x509.Certificate:
    try:
        certificate = x509.load_pem_x509_certificate(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ConfigurationError(f"The certificate at '{path}' could not be read as a PEM certificate.") from exc
    return certificate


def create_node_identity(identity_dir: Path, node_id: str) -> NodeIdentity:
    if not is_valid_node_id(node_id):
        raise ConfigurationError("A node ID must use 1 to 63 lowercase letters, digits or hyphens.")
    existing = [name for name in (IDENTITY_FILE_NAME, KEY_FILE_NAME, CERTIFICATE_FILE_NAME) if (identity_dir / name).exists()]
    if existing:
        raise ConfigurationError(
            f"A node identity already exists in '{identity_dir}'. Existing identities are never replaced."
        )

    identity_dir.mkdir(parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, node_id)])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=CERTIFICATE_VALID_DAYS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    certificate_pem = certificate.public_bytes(serialization.Encoding.PEM)
    identity_record = {
        "node_id": node_id,
        "certificate_sha256": certificate_fingerprint(certificate),
    }
    _write_new_file(identity_dir / KEY_FILE_NAME, key_pem, private=True)
    _write_new_file(identity_dir / CERTIFICATE_FILE_NAME, certificate_pem, private=False)
    _write_new_file(
        identity_dir / IDENTITY_FILE_NAME,
        (json.dumps(identity_record, indent=2) + "\n").encode("utf-8"),
        private=False,
    )
    provision_attestation_key(identity_dir)
    return load_node_identity(identity_dir)


def load_node_identity(identity_dir: Path) -> NodeIdentity:
    key_path = identity_dir / KEY_FILE_NAME
    certificate_path = identity_dir / CERTIFICATE_FILE_NAME
    identity_path = identity_dir / IDENTITY_FILE_NAME
    if not all(path.is_file() for path in (key_path, certificate_path, identity_path)):
        raise ConfigurationError(
            f"No complete node identity was found in '{identity_dir}'. Create one with the node provisioning command. "
            "A node identity is never created automatically."
        )

    record = _read_identity_record(identity_path)
    certificate = load_certificate_file(certificate_path)
    key = _load_private_key(key_path)

    certificate_key = certificate.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    own_key = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    if certificate_key != own_key:
        raise ConfigurationError("The node key does not match the node certificate.")

    common_names = [attribute.value for attribute in certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME)]
    if common_names != [record["node_id"]]:
        raise ConfigurationError("The node certificate does not belong to the node ID in the identity record.")

    fingerprint = certificate_fingerprint(certificate)
    if fingerprint != record["certificate_sha256"]:
        raise ConfigurationError("The node certificate does not match the fingerprint in the identity record.")

    return NodeIdentity(
        node_id=record["node_id"],
        certificate_path=certificate_path,
        key_path=key_path,
        certificate_sha256=fingerprint,
    )


def _read_identity_record(path: Path) -> dict[str, str]:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"The node identity record at '{path}' could not be read.") from exc
    if not isinstance(record, dict) or set(record) != {"node_id", "certificate_sha256"}:
        raise ConfigurationError(f"The node identity record at '{path}' has an unexpected format.")
    if not isinstance(record["node_id"], str) or not is_valid_node_id(record["node_id"]):
        raise ConfigurationError(f"The node identity record at '{path}' contains an invalid node ID.")
    return record


def _load_private_key(path: Path) -> ec.EllipticCurvePrivateKey:
    try:
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    except (OSError, ValueError, TypeError, UnsupportedAlgorithm) as exc:
        raise ConfigurationError(f"The node key at '{path}' could not be read.") from exc
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        raise ConfigurationError(f"The node key at '{path}' is not a supported key type.")
    return key


def _write_new_file(path: Path, content: bytes, *, private: bool) -> None:
    mode = 0o600 if private else 0o644
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
