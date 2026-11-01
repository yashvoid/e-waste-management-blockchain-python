from pathlib import Path

from cryptography.hazmat.primitives import serialization

from app.config.errors import ConfigurationError
from app.config.shared_network import SharedNetworkConfig, TrustedNode, TrustEpoch
from app.node.identity import NodeIdentity, certificate_fingerprint, load_certificate_file, load_node_identity

PEER_CERTIFICATE_DIR_NAME = "peers"
TRUST_BUNDLE_FILE_NAME = "trusted-peers.pem"


def latest_epoch(shared_config: SharedNetworkConfig) -> TrustEpoch:
    return shared_config.trust_epochs[-1]


def _tls_trusted_nodes(shared_config: SharedNetworkConfig) -> tuple[TrustedNode, ...]:
    return tuple(node for node in latest_epoch(shared_config).nodes if node.status in ("active", "retired"))


def _listed_active_nodes(shared_config: SharedNetworkConfig) -> tuple[TrustedNode, ...]:
    return tuple(node for node in latest_epoch(shared_config).nodes if node.status == "active")


def import_peer_certificate(identity_dir: Path, shared_config: SharedNetworkConfig, certificate_path: Path) -> str:
    identity = load_node_identity(identity_dir)
    certificate = load_certificate_file(certificate_path)
    fingerprint = certificate_fingerprint(certificate)
    trusted = _trusted_node_for_fingerprint(shared_config, fingerprint)
    if trusted is None:
        raise ConfigurationError(
            "This certificate's fingerprint is not listed in the latest trust epoch of the shared network "
            "configuration. Verify the fingerprint with the operator before adding it."
        )
    if trusted.node_id == identity.node_id:
        raise ConfigurationError("This is this node's own certificate; peer certificates belong to other nodes.")

    destination = _peer_certificate_path(identity_dir, fingerprint)
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    return trusted.node_id


def require_listed_identity(identity: NodeIdentity, shared_config: SharedNetworkConfig) -> None:
    listed = _trusted_node_for_fingerprint(shared_config, identity.certificate_sha256)
    if listed is None or listed.node_id != identity.node_id or listed.status != "active":
        raise ConfigurationError(
            f"The certificate for node '{identity.node_id}' is not listed as an active entry in the latest trust epoch "
            "of the shared network configuration. Its fingerprint must be agreed and listed before this node can start."
        )


def trusted_peer_certificates(
    identity_dir: Path, shared_config: SharedNetworkConfig, own_node_id: str
) -> dict[str, Path]:
    return {
        node.node_id: path
        for node in _listed_active_nodes(shared_config)
        if node.node_id != own_node_id
        for path in [_stored_certificate(identity_dir, shared_config, node)]
        if path is not None
    }


def accepted_certificate_paths(identity_dir: Path, shared_config: SharedNetworkConfig, own_node_id: str) -> list[Path]:
    paths: list[Path] = []
    for node in _tls_trusted_nodes(shared_config):
        if node.node_id == own_node_id:
            continue
        path = _stored_certificate(identity_dir, shared_config, node)
        if path is not None:
            paths.append(path)
    return paths


def write_trust_bundle(identity_dir: Path, certificate_paths: list[Path]) -> Path:
    bundle = identity_dir / TRUST_BUNDLE_FILE_NAME
    bundle.write_bytes(b"".join(path.read_bytes() for path in sorted(certificate_paths)))
    return bundle


def _stored_certificate(identity_dir: Path, shared_config: SharedNetworkConfig, node: TrustedNode) -> Path | None:
    path = _peer_certificate_path(identity_dir, node.tls_certificate_sha256)
    if not path.is_file():
        return None
    if certificate_fingerprint(load_certificate_file(path)) != node.tls_certificate_sha256:
        raise ConfigurationError(
            f"The stored certificate for node '{node.node_id}' does not match the shared network configuration."
        )
    return path


def _trusted_node_for_fingerprint(shared_config: SharedNetworkConfig, fingerprint: str) -> TrustedNode | None:
    for node in latest_epoch(shared_config).nodes:
        if node.tls_certificate_sha256 == fingerprint:
            return node
    return None


def _peer_certificate_path(identity_dir: Path, fingerprint: str) -> Path:
    return identity_dir / PEER_CERTIFICATE_DIR_NAME / f"{fingerprint}.pem"
