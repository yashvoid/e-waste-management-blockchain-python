import hashlib

from coincurve import PublicKey
from coincurve.ecdsa import cdata_to_der, deserialize_compact

from app.crypto.hexutil import hex_to_bytes

TRANSACTION_TAG = "EWASTE-TX-V1"
BLOCK_TAG = "EWASTE-BLOCK-V1"
ADDRESS_TAG = "EWASTE-ADDRESS-V1"
TRANSACTION_ROOT_TAG = "EWASTE-BLOCK-TXROOT-V1"

CURVE_ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
HALF_ORDER = CURVE_ORDER >> 1


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def domain_hash(tag: str, payload: bytes) -> bytes:
    return sha256(tag.encode("ascii") + b"\x00" + payload)


def parse_compressed_public_key(public_key_hex: str) -> bytes:
    data = hex_to_bytes(public_key_hex, 33)
    if data[0] not in (0x02, 0x03):
        raise ValueError("Public key must be compressed.")
    PublicKey(data)
    return data


def parse_compact_signature(signature_hex: str) -> bytes:
    data = hex_to_bytes(signature_hex, 64)
    r = int.from_bytes(data[:32], "big")
    s = int.from_bytes(data[32:], "big")
    if r < 1 or r >= CURVE_ORDER:
        raise ValueError("Signature r is out of range.")
    if s < 1 or s > HALF_ORDER:
        raise ValueError("Signature s must be low-S.")
    return data


def wallet_address_from_public_key(public_key_hex: str) -> str:
    public_key = parse_compressed_public_key(public_key_hex)
    return domain_hash(ADDRESS_TAG, public_key)[:20].hex()


def verify_digest(public_key_hex: str, digest: bytes, signature_hex: str) -> bool:
    if len(digest) != 32:
        return False
    try:
        public_key = parse_compressed_public_key(public_key_hex)
        signature = parse_compact_signature(signature_hex)
        der_signature = cdata_to_der(deserialize_compact(signature))
        return PublicKey(public_key).verify(der_signature, digest, hasher=None)
    except ValueError:
        return False
