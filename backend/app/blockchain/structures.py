import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.crypto.canonical import canonical_bytes
from app.crypto.secp256k1 import BLOCK_TAG, TRANSACTION_ROOT_TAG, TRANSACTION_TAG, domain_hash

MIN_DIFFICULTY = 1
MAX_DIFFICULTY = 32
GENESIS_PREVIOUS_HASH = "0" * 64

_TIMESTAMP_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def parse_utc_timestamp(text: object) -> datetime:
    if not isinstance(text, str) or _TIMESTAMP_PATTERN.fullmatch(text) is None:
        raise ValueError("Timestamp must be UTC ISO 8601 with second precision ending in Z.")
    return datetime.strptime(text, _TIMESTAMP_FORMAT).replace(tzinfo=timezone.utc)


def meets_proof_of_work(block_hash: str, difficulty: int) -> bool:
    return int(block_hash, 16) < (1 << (256 - difficulty))


@dataclass(frozen=True)
class Transaction:
    network_id: str
    protocol_version: int
    timestamp: str
    sender_public_key: str
    tx_type: str
    payload: dict[str, Any]
    nonce: int
    txid: str
    signature: str

    def to_dict(self) -> dict[str, Any]:
        return {
            **transaction_body(
                self.network_id,
                self.protocol_version,
                self.timestamp,
                self.sender_public_key,
                self.tx_type,
                self.payload,
                self.nonce,
            ),
            "txid": self.txid,
            "signature": self.signature,
        }


def transaction_body(
    network_id: str,
    protocol_version: int,
    timestamp: str,
    sender_public_key: str,
    tx_type: str,
    payload: dict[str, Any],
    nonce: int,
) -> dict[str, Any]:
    return {
        "networkId": network_id,
        "protocolVersion": protocol_version,
        "timestamp": timestamp,
        "senderPublicKey": sender_public_key,
        "type": tx_type,
        "payload": payload,
        "nonce": nonce,
    }


def transaction_digest(body: dict[str, Any]) -> bytes:
    return domain_hash(TRANSACTION_TAG, canonical_bytes(body))


def make_transaction(
    network_id: str,
    protocol_version: int,
    timestamp: str,
    sender_public_key: str,
    tx_type: str,
    payload: dict[str, Any],
    nonce: int,
    signature: str,
) -> Transaction:
    body = transaction_body(network_id, protocol_version, timestamp, sender_public_key, tx_type, payload, nonce)
    return Transaction(
        network_id=network_id,
        protocol_version=protocol_version,
        timestamp=timestamp,
        sender_public_key=sender_public_key,
        tx_type=tx_type,
        payload=payload,
        nonce=nonce,
        txid=transaction_digest(body).hex(),
        signature=signature,
    )


def transaction_sort_key(transaction: Transaction) -> tuple[str, str]:
    return (transaction.timestamp, transaction.txid)


def compute_transaction_root(leaves: Sequence[tuple[str, str]]) -> str:
    entries = [{"signature": signature, "txid": txid} for txid, signature in leaves]
    return domain_hash(TRANSACTION_ROOT_TAG, canonical_bytes(entries)).hex()


def block_header_body(
    network_id: str,
    protocol_version: int,
    height: int,
    previous_hash: str,
    timestamp: str,
    difficulty: int,
    nonce: int,
    transaction_root: str,
) -> dict[str, Any]:
    return {
        "networkId": network_id,
        "protocolVersion": protocol_version,
        "height": height,
        "previousHash": previous_hash,
        "timestamp": timestamp,
        "difficulty": difficulty,
        "nonce": nonce,
        "transactionRoot": transaction_root,
    }


def block_hash_hex(header: dict[str, Any]) -> str:
    return domain_hash(BLOCK_TAG, canonical_bytes(header)).hex()


@dataclass(frozen=True)
class Block:
    network_id: str
    protocol_version: int
    height: int
    previous_hash: str
    timestamp: str
    difficulty: int
    nonce: int
    transaction_root: str
    block_hash: str
    transactions: tuple[Transaction, ...]

    def header(self) -> dict[str, Any]:
        return block_header_body(
            self.network_id,
            self.protocol_version,
            self.height,
            self.previous_hash,
            self.timestamp,
            self.difficulty,
            self.nonce,
            self.transaction_root,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.header(),
            "hash": self.block_hash,
            "transactions": [transaction.to_dict() for transaction in self.transactions],
        }


def make_block(
    network_id: str,
    protocol_version: int,
    height: int,
    previous_hash: str,
    timestamp: str,
    difficulty: int,
    nonce: int,
    transactions: Sequence[Transaction],
) -> Block:
    transaction_root = compute_transaction_root([(transaction.txid, transaction.signature) for transaction in transactions])
    header = block_header_body(
        network_id,
        protocol_version,
        height,
        previous_hash,
        timestamp,
        difficulty,
        nonce,
        transaction_root,
    )
    return Block(
        network_id=network_id,
        protocol_version=protocol_version,
        height=height,
        previous_hash=previous_hash,
        timestamp=timestamp,
        difficulty=difficulty,
        nonce=nonce,
        transaction_root=transaction_root,
        block_hash=block_hash_hex(header),
        transactions=tuple(transactions),
    )


def make_genesis_block(
    network_id: str,
    protocol_version: int,
    timestamp: str,
    difficulty: int,
    nonce: int,
) -> Block:
    return make_block(
        network_id=network_id,
        protocol_version=protocol_version,
        height=0,
        previous_hash=GENESIS_PREVIOUS_HASH,
        timestamp=timestamp,
        difficulty=difficulty,
        nonce=nonce,
        transactions=(),
    )


def block_work(block: Block) -> int:
    return 1 << block.difficulty


class BlockStore:
    def __init__(self, genesis: Block) -> None:
        self.blocks_by_hash: dict[str, Block] = {genesis.block_hash: genesis}
        self.canonical_chain: list[Block] = [genesis]

    @property
    def tip(self) -> Block:
        return self.canonical_chain[-1]

    def is_canonical(self, block: Block) -> bool:
        return (
            block.height < len(self.canonical_chain)
            and self.canonical_chain[block.height].block_hash == block.block_hash
        )

    def ancestry(self, block: Block) -> list[Block]:
        chain = [block]
        current = block
        while current.height > 0:
            current = self.blocks_by_hash[current.previous_hash]
            chain.append(current)
        return chain

    def cumulative_work(self, block: Block) -> int:
        return sum(block_work(ancestor) for ancestor in self.ancestry(block) if ancestor.height > 0)
