import json
from typing import Any

from app.blockchain.structures import Block, Transaction
from app.storage.errors import StorageError

_BLOCK_KEYS = frozenset(
    {
        "networkId",
        "protocolVersion",
        "height",
        "previousHash",
        "timestamp",
        "difficulty",
        "nonce",
        "transactionRoot",
        "hash",
        "transactions",
    }
)
_TRANSACTION_KEYS = frozenset(
    {
        "networkId",
        "protocolVersion",
        "timestamp",
        "senderPublicKey",
        "type",
        "payload",
        "nonce",
        "txid",
        "signature",
    }
)


def encode_block_record(block: Block) -> str:
    return (
        json.dumps(block.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    )


def decode_block_record(line: str) -> Block:
    try:
        raw: Any = json.loads(line)
    except ValueError as exc:
        raise StorageError("A complete stored block record is not valid JSON.") from exc
    return decode_block_object(raw)


def decode_block_object(raw: Any) -> Block:
    if not isinstance(raw, dict) or set(raw) != _BLOCK_KEYS or not isinstance(raw["transactions"], list):
        raise StorageError("A complete stored block record does not have the required block structure.")
    return Block(
        network_id=raw["networkId"],
        protocol_version=raw["protocolVersion"],
        height=raw["height"],
        previous_hash=raw["previousHash"],
        timestamp=raw["timestamp"],
        difficulty=raw["difficulty"],
        nonce=raw["nonce"],
        transaction_root=raw["transactionRoot"],
        block_hash=raw["hash"],
        transactions=tuple(decode_transaction_object(item) for item in raw["transactions"]),
    )


def decode_transaction_object(raw: Any) -> Transaction:
    if not isinstance(raw, dict) or set(raw) != _TRANSACTION_KEYS:
        raise StorageError("A stored transaction does not have the required structure.")
    return Transaction(
        network_id=raw["networkId"],
        protocol_version=raw["protocolVersion"],
        timestamp=raw["timestamp"],
        sender_public_key=raw["senderPublicKey"],
        tx_type=raw["type"],
        payload=raw["payload"],
        nonce=raw["nonce"],
        txid=raw["txid"],
        signature=raw["signature"],
    )
