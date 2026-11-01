import hashlib
import threading

from coincurve import PrivateKey
from coincurve.ecdsa import der_to_cdata, serialize_compact
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.blockchain.mining import add_block, mine_block
from app.blockchain.structures import (
    Block,
    BlockStore,
    Transaction,
    make_genesis_block,
    make_transaction,
    meets_proof_of_work,
    transaction_body,
    transaction_digest,
)
from app.config.shared_network import SharedNetworkConfig

TEST_GENESIS_TIMESTAMP = "2026-01-01T00:00:00Z"


def _mined_genesis_nonce(network_id: str, protocol_version: int, timestamp: str, difficulty: int) -> int:
    nonce = 0
    while not meets_proof_of_work(
        make_genesis_block(network_id, protocol_version, timestamp, difficulty, nonce).block_hash, difficulty
    ):
        nonce += 1
    return nonce


def shared_network_values(difficulty: int = 1, **changes: object) -> dict[str, object]:
    network_id = str(changes.get("network_id", "test-network"))
    protocol_version = int(changes.get("protocol_version", 1))
    timestamp = str(changes.get("genesis_timestamp", TEST_GENESIS_TIMESTAMP))
    genesis_nonce = _mined_genesis_nonce(network_id, protocol_version, timestamp, difficulty)
    genesis = make_genesis_block(network_id, protocol_version, timestamp, difficulty, genesis_nonce)
    return {
        "network_id": network_id,
        "protocol_version": protocol_version,
        "genesis_timestamp": timestamp,
        "genesis_nonce": genesis_nonce,
        "genesis_hash": genesis.block_hash,
        "initial_difficulty": difficulty,
        "max_transactions_per_block": 100,
        "max_block_size_bytes": 1024 * 1024,
        "max_transaction_payload_bytes": 16 * 1024,
        "trust_epochs": [],
    }


def shared_network_config(difficulty: int = 1) -> SharedNetworkConfig:
    return SharedNetworkConfig(**{**shared_network_values(difficulty), "trust_epochs": ()})


def attestation_key_hex(label: str) -> str:
    private_value = int.from_bytes(hashlib.sha256(f"attestation:{label}".encode("utf-8")).digest(), "big")
    key = ec.derive_private_key(private_value, ec.SECP256R1())
    return key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.CompressedPoint).hex()


def key_for_label(label: str) -> bytes:
    return hashlib.sha256(label.encode("utf-8")).digest()


def sign_transaction(
    config: SharedNetworkConfig,
    private_key: bytes,
    timestamp: str,
    *,
    payload: dict[str, object] | None = None,
    nonce: int = 0,
    tx_type: str = "test-event",
) -> Transaction:
    signer = PrivateKey(private_key)
    public_key = signer.public_key.format(compressed=True).hex()
    payload = {"reference": "test"} if payload is None else payload
    body = transaction_body(config.network_id, config.protocol_version, timestamp, public_key, tx_type, payload, nonce)
    digest = transaction_digest(body)
    signature = serialize_compact(der_to_cdata(signer.sign(digest, hasher=None))).hex()
    return make_transaction(
        config.network_id,
        config.protocol_version,
        timestamp,
        public_key,
        tx_type,
        payload,
        nonce,
        signature,
    )


def mine(config: SharedNetworkConfig, parent: Block, transactions: list[Transaction], timestamp: str) -> Block:
    block = mine_block(config, parent, transactions, timestamp, threading.Event())
    assert block is not None
    return block


def mine_and_add(
    store: BlockStore,
    config: SharedNetworkConfig,
    parent: Block,
    transactions: list[Transaction],
    timestamp: str,
):
    block = mine(config, parent, transactions, timestamp)
    return block, add_block(store, config, block)
