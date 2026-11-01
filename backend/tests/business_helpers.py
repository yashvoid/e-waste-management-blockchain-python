from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from coincurve import PrivateKey
from coincurve.ecdsa import der_to_cdata, serialize_compact

from app.blockchain.business import (
    BATCH_CREATE_TYPE,
    TRANSFER_ACCEPT_TYPE,
    TRANSFER_CANCEL_TYPE,
    TRANSFER_REJECT_TYPE,
    TRANSFER_REQUEST_TYPE,
    loss_approval_digest,
)
from app.blockchain.participants import REGISTER_TYPE, SUSPEND_TYPE
from app.blockchain.processing import CORRECTION_TYPE, PROCESS_TYPE
from app.config.shared_network import TrustEpoch, TrustedNode
from app.node.attestation import (
    PURPOSE_REGISTRATION,
    attestation_public_key_hex,
    issue_attestation,
    load_attestation_key,
)
from chain_helpers import key_for_label, shared_network_config, sign_transaction
from node_helpers import create_identities

ISSUED = "2026-01-01T00:00:30Z"
BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)

GEN = "gen"
COL = "col"
TRA = "tra"
REC = "rec"
MP = "mp"


def make_network(root: Path):
    identities = create_identities(root, ["node-a", "node-b"])
    listed = tuple(
        TrustedNode(
            node_id,
            identity.certificate_sha256,
            attestation_public_key_hex(load_attestation_key(identity.key_path.parent)),
            "active",
        )
        for node_id, identity in identities.items()
    )
    config = replace(shared_network_config(), trust_epochs=(TrustEpoch(0, 0, listed),))
    return identities, config


def wallet_key(label: str) -> bytes:
    return key_for_label(label)


def wallet_pub(label: str) -> str:
    return PrivateKey(wallet_key(label)).public_key.format(compressed=True).hex()


def at(*, minutes: int = 0, hours: int = 0, seconds: int = 0) -> str:
    moment = BASE + timedelta(hours=hours, minutes=minutes, seconds=seconds)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _tx(config, label: str, tx_type: str, payload: dict, nonce: int):
    return sign_transaction(config, wallet_key(label), ISSUED, payload=payload, nonce=nonce, tx_type=tx_type)


def register_tx(network, label: str, role: str):
    identities, config = network
    attestation = issue_attestation(
        identities["node-a"].key_path.parent,
        config,
        node_id="node-a",
        purpose=PURPOSE_REGISTRATION,
        wallet_public_key=wallet_pub(label),
        role=role,
        request_id=f"req-{label}",
        nonce=f"reg-{label}",
        issued_at=ISSUED,
    )
    return _tx(config, label, REGISTER_TYPE, {"attestation": attestation.to_dict()}, 0)


def suspend_tx(config, label: str):
    return _tx(config, label, SUSPEND_TYPE, {}, 1)


def batch_tx(config, label: str, grams: object, *, description: object = "Old laptops", nonce: int = 0):
    return _tx(config, label, BATCH_CREATE_TYPE, {"description": description, "quantityGrams": grams}, nonce)


def request_tx(config, sender: str, batch_id: str, receiver: str, grams: object, *, nonce: int = 0):
    payload = {"batchId": batch_id, "receiverPublicKey": wallet_pub(receiver), "quantityGrams": grams}
    return _tx(config, sender, TRANSFER_REQUEST_TYPE, payload, nonce)


def accept_tx(config, receiver: str, transfer_id: str, actual: object, *, reason: str = "", approval: str = "", nonce: int = 0):
    payload = {"transferId": transfer_id, "actualGrams": actual, "reason": reason, "senderApproval": approval}
    return _tx(config, receiver, TRANSFER_ACCEPT_TYPE, payload, nonce)


def reject_tx(config, receiver: str, transfer_id: str, reason: str, *, nonce: int = 0):
    return _tx(config, receiver, TRANSFER_REJECT_TYPE, {"transferId": transfer_id, "reason": reason}, nonce)


def cancel_tx(config, sender: str, transfer_id: str, *, nonce: int = 0):
    return _tx(config, sender, TRANSFER_CANCEL_TYPE, {"transferId": transfer_id}, nonce)


def loss_approval(sender: str, transfer_id: str, reason: str) -> str:
    signer = PrivateKey(wallet_key(sender))
    return serialize_compact(der_to_cdata(signer.sign(loss_approval_digest(transfer_id, reason), hasher=None))).hex()


def apply_block(ledger, config, transactions, when: str) -> None:
    ledger.begin_block(when)
    for transaction in transactions:
        ledger.apply(transaction, block_timestamp=when, height=1, config=config)


def process_tx(
    config,
    label: str,
    input_item: str,
    input_grams: object,
    outputs: list[tuple[object, object]],
    residual: object,
    *,
    method: object = "",
    nonce: int = 0,
):
    payload = {
        "inputItemId": input_item,
        "inputGrams": input_grams,
        "outputs": [{"description": text, "quantityGrams": grams} for text, grams in outputs],
        "residualGrams": residual,
        "method": method,
    }
    return _tx(config, label, PROCESS_TYPE, payload, nonce)


def correction_tx(config, label: str, target_id: str, explanation: object, *, nonce: int = 0):
    return _tx(config, label, CORRECTION_TYPE, {"targetId": target_id, "explanation": explanation}, nonce)


def deliver_to_recycler(ledger, network, grams: int = 100_000, *, label: str = "batch") -> str:
    _, config = network
    batch = batch_tx(config, GEN, grams, description=label)
    apply_block(ledger, config, [batch], at(minutes=2))
    hops = ((GEN, COL), (COL, TRA), (TRA, REC))
    for step, (sender, receiver) in enumerate(hops):
        request = request_tx(config, sender, batch.txid, receiver, grams, nonce=step)
        apply_block(ledger, config, [request], at(minutes=3 + step * 2))
        accept = accept_tx(config, receiver, request.txid, grams)
        apply_block(ledger, config, [accept], at(minutes=4 + step * 2))
    return batch.txid


def transfer_material_to_processor(ledger, network, material_id: str, grams: int, *, minute: int, nonce: int = 0):
    _, config = network
    request = request_tx(config, REC, material_id, MP, grams, nonce=nonce)
    apply_block(ledger, config, [request], at(minutes=minute))
    accept = accept_tx(config, MP, request.txid, grams)
    apply_block(ledger, config, [accept], at(minutes=minute + 1))
    return request.txid
