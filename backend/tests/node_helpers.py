import socket
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from app.config.node_settings import PeerAddress
from app.config.shared_network import SharedNetworkConfig, TrustedNode, TrustEpoch
from app.node.attestation import attestation_public_key_hex, load_attestation_key
from app.node.identity import NodeIdentity, create_node_identity
from app.node.peer_server import PeerListener, create_peer_app
from app.node.peer_tls import client_ssl_context
from app.node.peer_trust import import_peer_certificate, trusted_peer_certificates, write_trust_bundle
from app.node.pending_pool import PendingTransactionPool
from app.node.transaction_relay import TransactionRelay
from app.storage.chain_storage import ChainStorage, open_chain_storage
from chain_helpers import shared_network_values


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def create_identities(root: Path, node_ids: list[str]) -> dict[str, NodeIdentity]:
    return {node_id: create_node_identity(root / "identities" / node_id, node_id) for node_id in node_ids}


def attestation_public_key_for(identity: NodeIdentity) -> str:
    return attestation_public_key_hex(load_attestation_key(identity.key_path.parent))


def network_config(identities: Mapping[str, NodeIdentity], **overrides: object) -> SharedNetworkConfig:
    nodes = tuple(
        TrustedNode(
            node_id=identity.node_id,
            tls_certificate_sha256=identity.certificate_sha256,
            attestation_public_key=attestation_public_key_for(identity),
            status="active",
        )
        for identity in identities.values()
    )
    epochs = (TrustEpoch(epoch=0, activation_height=0, nodes=nodes),)
    return SharedNetworkConfig(**{**shared_network_values(**overrides), "trust_epochs": epochs})


def provision_peers(
    identities: Mapping[str, NodeIdentity], config: SharedNetworkConfig, node_id: str, peer_ids: list[str]
) -> dict[str, Path]:
    identity_dir = identities[node_id].certificate_path.parent
    for peer_id in peer_ids:
        import_peer_certificate(identity_dir, config, identities[peer_id].certificate_path)
    return trusted_peer_certificates(identity_dir, config, node_id)


def start_peer_service(
    identity: NodeIdentity,
    config: SharedNetworkConfig,
    port: int,
    trusted_certificates: Mapping[str, Path],
    storage: ChainStorage,
    relay: TransactionRelay,
) -> PeerListener:
    bundle = write_trust_bundle(identity.certificate_path.parent, list(trusted_certificates.values()))
    listener = PeerListener(
        app=create_peer_app(identity, config, storage, relay),
        host="127.0.0.1",
        port=port,
        identity=identity,
        trust_bundle=bundle,
    )
    listener.start()
    return listener


@dataclass(frozen=True)
class RunningNode:
    storage: ChainStorage
    pool: PendingTransactionPool
    relay: TransactionRelay


@contextmanager
def running_node(
    identity: NodeIdentity,
    config: SharedNetworkConfig,
    port: int,
    trusted_certificates: Mapping[str, Path],
    data_dir: Path,
    peers: Sequence[PeerAddress] = (),
) -> Iterator[RunningNode]:
    contexts = {node_id: client_ssl_context(identity, path) for node_id, path in trusted_certificates.items()}
    with open_chain_storage(data_dir, config) as storage:
        pool = PendingTransactionPool(storage)
        relay = TransactionRelay(
            node_id=identity.node_id,
            pool=pool,
            peers=peers,
            contexts=contexts,
            timeout_seconds=3.0,
        )
        listener = start_peer_service(identity, config, port, trusted_certificates, storage, relay)
        try:
            yield RunningNode(storage=storage, pool=pool, relay=relay)
        finally:
            listener.stop()
            relay.close()


@contextmanager
def running_peer(
    identity: NodeIdentity,
    config: SharedNetworkConfig,
    port: int,
    trusted_certificates: Mapping[str, Path],
    data_dir: Path,
) -> Iterator[ChainStorage]:
    with running_node(identity, config, port, trusted_certificates, data_dir) as node:
        yield node.storage
