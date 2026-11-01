from collections.abc import Sequence
from datetime import datetime, timedelta

from app.blockchain.ledger import ChainLedger
from app.blockchain.participants import ParticipantRuleError
from app.blockchain.structures import (
    MAX_DIFFICULTY,
    MIN_DIFFICULTY,
    Block,
    Transaction,
    block_hash_hex,
    compute_transaction_root,
    make_genesis_block,
    meets_proof_of_work,
    parse_utc_timestamp,
    transaction_body,
    transaction_digest,
    transaction_sort_key,
)
from app.config.shared_network import SharedNetworkConfig
from app.crypto.canonical import MAX_SAFE_INTEGER, canonical_bytes
from app.crypto.secp256k1 import parse_compressed_public_key, verify_digest

MEDIAN_WINDOW = 11
MAX_TIMESTAMP_ADVANCE = timedelta(hours=2)


class ValidationError(ValueError):
    pass


def _is_integer(value: object) -> bool:
    return type(value) is int


def _canonical_length(value: object, description: str) -> int:
    try:
        return len(canonical_bytes(value))
    except ValueError as exc:
        raise ValidationError(f"The {description} cannot be serialized canonically.") from exc


def _parse_timestamp(text: object, description: str) -> datetime:
    try:
        return parse_utc_timestamp(text)
    except ValueError as exc:
        raise ValidationError(f"The {description} is not a valid UTC timestamp.") from exc


def validate_transaction(transaction: Transaction, config: SharedNetworkConfig) -> None:
    if transaction.network_id != config.network_id or transaction.protocol_version != config.protocol_version:
        raise ValidationError("A transaction belongs to a different network or protocol version.")
    _parse_timestamp(transaction.timestamp, "transaction timestamp")
    if not isinstance(transaction.tx_type, str) or not transaction.tx_type:
        raise ValidationError("A transaction type must be a non-empty text value.")
    if not _is_integer(transaction.nonce) or not 0 <= transaction.nonce <= MAX_SAFE_INTEGER:
        raise ValidationError("A transaction nonce must be a whole number within the safe range.")
    if not isinstance(transaction.payload, dict):
        raise ValidationError("A transaction payload must be a JSON object.")
    if _canonical_length(transaction.payload, "transaction payload") > config.max_transaction_payload_bytes:
        raise ValidationError("A transaction payload exceeds the maximum allowed size.")
    try:
        parse_compressed_public_key(transaction.sender_public_key)
    except ValueError as exc:
        raise ValidationError("A transaction sender public key is not a valid compressed key.") from exc

    body = transaction_body(
        transaction.network_id,
        transaction.protocol_version,
        transaction.timestamp,
        transaction.sender_public_key,
        transaction.tx_type,
        transaction.payload,
        transaction.nonce,
    )
    try:
        digest = transaction_digest(body)
    except ValueError as exc:
        raise ValidationError("A transaction body cannot be serialized canonically.") from exc

    if transaction.txid != digest.hex():
        raise ValidationError("A transaction ID does not match its signed content.")
    if not verify_digest(transaction.sender_public_key, digest, transaction.signature):
        raise ValidationError("A transaction signature is not valid for its sender public key.")


def upper_median(timestamps: Sequence[datetime]) -> datetime:
    ordered = sorted(timestamps)
    return ordered[len(ordered) // 2]


def validate_block(block: Block, config: SharedNetworkConfig, ancestors: Sequence[Block]) -> None:
    if block.network_id != config.network_id or block.protocol_version != config.protocol_version:
        raise ValidationError("A block belongs to a different network or protocol version.")

    parent = ancestors[0]
    if not _is_integer(block.height) or block.height != parent.height + 1:
        raise ValidationError("A block height does not follow its parent.")
    if block.previous_hash != parent.block_hash:
        raise ValidationError("A block does not reference its parent hash.")

    if not _is_integer(block.difficulty) or block.difficulty != config.initial_difficulty:
        raise ValidationError("A block difficulty does not match the configured network difficulty.")
    if not MIN_DIFFICULTY <= block.difficulty <= MAX_DIFFICULTY:
        raise ValidationError("A block difficulty is outside the allowed range.")
    if not _is_integer(block.nonce) or not 0 <= block.nonce <= MAX_SAFE_INTEGER:
        raise ValidationError("A block nonce must be a whole number within the safe range.")

    timestamp = _parse_timestamp(block.timestamp, "block timestamp")
    parent_timestamp = _parse_timestamp(parent.timestamp, "parent timestamp")
    window = [_parse_timestamp(ancestor.timestamp, "ancestor timestamp") for ancestor in ancestors[:MEDIAN_WINDOW]]
    if timestamp <= parent_timestamp:
        raise ValidationError("A block timestamp must be later than its parent timestamp.")
    if timestamp <= upper_median(window):
        raise ValidationError("A block timestamp must be later than the median of the preceding blocks.")
    if timestamp - parent_timestamp > MAX_TIMESTAMP_ADVANCE:
        raise ValidationError("A block timestamp is too far ahead of its parent timestamp.")

    if len(block.transactions) > config.max_transactions_per_block:
        raise ValidationError("A block contains more transactions than the maximum allowed.")
    for transaction in block.transactions:
        validate_transaction(transaction, config)

    txids = [transaction.txid for transaction in block.transactions]
    if len(set(txids)) != len(txids):
        raise ValidationError("A block contains the same transaction more than once.")
    ancestor_txids = {transaction.txid for ancestor in ancestors for transaction in ancestor.transactions}
    if ancestor_txids.intersection(txids):
        raise ValidationError("A block repeats a transaction already confirmed in its ancestry.")
    keys = [transaction_sort_key(transaction) for transaction in block.transactions]
    if keys != sorted(keys):
        raise ValidationError("Block transactions are not in the required timestamp and ID order.")

    ledger = ChainLedger.from_blocks(reversed(ancestors), config)
    ledger.begin_block(block.timestamp)
    for transaction in block.transactions:
        try:
            ledger.apply(transaction, block_timestamp=block.timestamp, height=block.height, config=config)
        except ParticipantRuleError as exc:
            raise ValidationError(str(exc)) from exc

    if block.transaction_root != compute_transaction_root([(tx.txid, tx.signature) for tx in block.transactions]):
        raise ValidationError("A block transaction root does not match its transactions.")
    if block.block_hash != block_hash_hex(block.header()):
        raise ValidationError("A block hash does not match its header.")
    if not meets_proof_of_work(block.block_hash, block.difficulty):
        raise ValidationError("A block does not meet the proof-of-work requirement.")

    if _canonical_length(block.to_dict(), "block") > config.max_block_size_bytes:
        raise ValidationError("A block exceeds the maximum allowed size.")


def verify_genesis(config: SharedNetworkConfig) -> Block:
    genesis = make_genesis_block(
        network_id=config.network_id,
        protocol_version=config.protocol_version,
        timestamp=config.genesis_timestamp,
        difficulty=config.initial_difficulty,
        nonce=config.genesis_nonce,
    )
    if genesis.block_hash != config.genesis_hash:
        raise ValidationError("The derived genesis hash does not match the configured genesis hash.")
    if not meets_proof_of_work(genesis.block_hash, genesis.difficulty):
        raise ValidationError("The configured genesis does not meet its proof-of-work requirement.")
    return genesis
