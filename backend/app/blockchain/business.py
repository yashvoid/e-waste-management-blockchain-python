from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from app.blockchain.participants import ParticipantLedger, ParticipantRuleError, require_payload_keys
from app.blockchain.structures import Transaction
from app.crypto.canonical import MAX_SAFE_INTEGER, canonical_bytes
from app.crypto.secp256k1 import domain_hash, verify_digest

BATCH_CREATE_TYPE = "batch.create"
TRANSFER_REQUEST_TYPE = "transfer.request"
TRANSFER_ACCEPT_TYPE = "transfer.accept"
TRANSFER_REJECT_TYPE = "transfer.reject"
TRANSFER_CANCEL_TYPE = "transfer.cancel"
BUSINESS_TYPES = frozenset(
    {BATCH_CREATE_TYPE, TRANSFER_REQUEST_TYPE, TRANSFER_ACCEPT_TYPE, TRANSFER_REJECT_TYPE, TRANSFER_CANCEL_TYPE}
)

GENERATOR_ROLE = "Generator"
RECYCLER_ROLE = "Recycler"
MATERIAL_PROCESSOR_ROLE = "Material Processor"
NEXT_ROLE = {"Generator": "Collector", "Collector": "Transporter", "Transporter": "Recycler", "Recycler": "Material Processor"}
TRANSFER_WINDOW = timedelta(hours=48)
MAX_TEXT_LENGTH = 500
LOSS_APPROVAL_TAG = "EWASTE-LOSS-APPROVAL-V1"

PENDING = "pending"
ACCEPTED = "accepted"
REJECTED = "rejected"
CANCELLED = "cancelled"
EXPIRED = "expired"


@dataclass(frozen=True)
class Batch:
    batch_id: str
    generator: str
    description: str
    quantity_grams: int
    created_at: datetime


@dataclass(frozen=True)
class Transfer:
    transfer_id: str
    batch_id: str
    sender: str
    receiver: str
    declared_grams: int
    requested_at: datetime
    expires_at: datetime
    status: str = PENDING
    actual_grams: int | None = None
    reason: str = ""


def loss_approval_digest(transfer_id: str, reason: str) -> bytes:
    body = {"transferId": transfer_id, "reason": reason, "actualGrams": 0}
    return domain_hash(LOSS_APPROVAL_TAG, canonical_bytes(body))


def require_grams(value: object, description: str) -> int:
    if type(value) is not int or not 0 < value <= MAX_SAFE_INTEGER:
        raise ParticipantRuleError(f"The {description} must be a positive whole number of grams.")
    return value


def require_text(value: object, description: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_TEXT_LENGTH:
        raise ParticipantRuleError(f"The {description} must be between 1 and {MAX_TEXT_LENGTH} characters.")
    return value


class BusinessLedger:
    def __init__(self, participants: ParticipantLedger) -> None:
        self._participants = participants
        self._batches: dict[str, Batch] = {}
        self._transfers: dict[str, Transfer] = {}
        self._holdings: dict[tuple[str, str], int] = {}
        self._discrepancies: dict[str, int] = {}
        self._materials: set[str] = set()

    def batch(self, batch_id: str) -> Batch | None:
        return self._batches.get(batch_id)

    def batches(self) -> tuple[Batch, ...]:
        return tuple(self._batches.values())

    def transfer(self, transfer_id: str) -> Transfer | None:
        return self._transfers.get(transfer_id)

    def transfers(self) -> tuple[Transfer, ...]:
        return tuple(self._transfers.values())

    def holding(self, holder: str, batch_id: str) -> int:
        return self._holdings.get((holder, batch_id), 0)

    def reserved(self, holder: str, batch_id: str) -> int:
        return sum(
            transfer.declared_grams
            for transfer in self._transfers.values()
            if transfer.status == PENDING and transfer.sender == holder and transfer.batch_id == batch_id
        )

    def available(self, holder: str, batch_id: str) -> int:
        return self.holding(holder, batch_id) - self.reserved(holder, batch_id)

    def register_material(self, material_id: str) -> None:
        self._materials.add(material_id)

    def total_held(self, item_id: str) -> int:
        return sum(grams for (_, held_item), grams in self._holdings.items() if held_item == item_id)

    def discrepancy(self, batch_id: str) -> int:
        return self._discrepancies.get(batch_id, 0)

    def expire_due(self, when: datetime) -> None:
        for transfer_id, transfer in list(self._transfers.items()):
            if transfer.status == PENDING and transfer.expires_at <= when:
                self._transfers[transfer_id] = replace(transfer, status=EXPIRED)

    def check(self, transaction: Transaction, when: datetime) -> None:
        kind = transaction.tx_type
        if kind == BATCH_CREATE_TYPE:
            self._check_batch_create(transaction)
        elif kind == TRANSFER_REQUEST_TYPE:
            self._check_transfer_request(transaction)
        elif kind == TRANSFER_ACCEPT_TYPE:
            self._check_transfer_accept(transaction, when)
        elif kind == TRANSFER_REJECT_TYPE:
            self._check_transfer_reject(transaction)
        elif kind == TRANSFER_CANCEL_TYPE:
            self._check_transfer_cancel(transaction)

    def apply(self, transaction: Transaction, when: datetime) -> None:
        payload = transaction.payload
        sender = transaction.sender_public_key
        kind = transaction.tx_type
        if kind == BATCH_CREATE_TYPE:
            grams = payload["quantityGrams"]
            self._batches[transaction.txid] = Batch(
                batch_id=transaction.txid,
                generator=sender,
                description=payload["description"],
                quantity_grams=grams,
                created_at=when,
            )
            self.add_holding(sender, transaction.txid, grams)
        elif kind == TRANSFER_REQUEST_TYPE:
            self._transfers[transaction.txid] = Transfer(
                transfer_id=transaction.txid,
                batch_id=payload["batchId"],
                sender=sender,
                receiver=payload["receiverPublicKey"],
                declared_grams=payload["quantityGrams"],
                requested_at=when,
                expires_at=when + TRANSFER_WINDOW,
            )
        elif kind == TRANSFER_ACCEPT_TYPE:
            transfer = self._pending(payload["transferId"])
            actual = payload["actualGrams"]
            self.add_holding(transfer.sender, transfer.batch_id, -transfer.declared_grams)
            self.add_holding(transfer.receiver, transfer.batch_id, actual)
            self._discrepancies[transfer.batch_id] = (
                self.discrepancy(transfer.batch_id) + transfer.declared_grams - actual
            )
            self._transfers[transfer.transfer_id] = replace(
                transfer, status=ACCEPTED, actual_grams=actual, reason=payload["reason"]
            )
        elif kind == TRANSFER_REJECT_TYPE:
            transfer = self._pending(payload["transferId"])
            self._transfers[transfer.transfer_id] = replace(transfer, status=REJECTED, reason=payload["reason"])
        elif kind == TRANSFER_CANCEL_TYPE:
            transfer = self._pending(payload["transferId"])
            self._transfers[transfer.transfer_id] = replace(transfer, status=CANCELLED)

    def add_holding(self, holder: str, batch_id: str, delta: int) -> None:
        key = (holder, batch_id)
        self._holdings[key] = self._holdings.get(key, 0) + delta

    def _pending(self, transfer_id: object) -> Transfer:
        transfer = self._transfers.get(transfer_id) if isinstance(transfer_id, str) else None
        if transfer is None or transfer.status != PENDING:
            raise ParticipantRuleError("This transfer does not exist or is no longer pending.")
        return transfer

    def _check_batch_create(self, transaction: Transaction) -> None:
        require_payload_keys(transaction, {"description", "quantityGrams"})
        generator = self._participants.participant(transaction.sender_public_key)
        if generator is None or generator.role != GENERATOR_ROLE:
            raise ParticipantRuleError("Only a registered Generator can create an e-waste batch.")
        require_text(transaction.payload["description"], "e-waste description")
        require_grams(transaction.payload["quantityGrams"], "batch quantity")

    def _check_transfer_request(self, transaction: Transaction) -> None:
        require_payload_keys(transaction, {"batchId", "receiverPublicKey", "quantityGrams"})
        payload = transaction.payload
        item_id = payload["batchId"]
        is_material = isinstance(item_id, str) and item_id in self._materials
        if not is_material and (not isinstance(item_id, str) or item_id not in self._batches):
            raise ParticipantRuleError("The batch or material does not exist on the accepted chain.")
        grams = require_grams(payload["quantityGrams"], "transfer quantity")
        receiver_key = payload["receiverPublicKey"]
        if receiver_key == transaction.sender_public_key:
            raise ParticipantRuleError("A sender cannot transfer to themselves.")
        sender = self._participants.participant(transaction.sender_public_key)
        if sender is None:
            raise ParticipantRuleError("Only a registered wallet can request a transfer.")
        if is_material and sender.role != RECYCLER_ROLE:
            raise ParticipantRuleError("Recovered material can only be transferred by a Recycler to a Material Processor.")
        if not is_material and sender.role == RECYCLER_ROLE:
            raise ParticipantRuleError("A Recycler can only transfer recovered material to a Material Processor.")
        next_role = NEXT_ROLE.get(sender.role)
        if next_role is None:
            raise ParticipantRuleError("This role cannot start a custody transfer in this version.")
        receiver = self._participants.participant(receiver_key) if isinstance(receiver_key, str) else None
        if receiver is None or receiver.suspended:
            raise ParticipantRuleError("The receiver must be a registered, active participant.")
        if receiver.role != next_role:
            raise ParticipantRuleError(f"A {sender.role} can only transfer to a {next_role}.")
        if self.available(transaction.sender_public_key, item_id) < grams:
            raise ParticipantRuleError("The requested quantity exceeds the available unreserved quantity.")

    def _check_transfer_accept(self, transaction: Transaction, when: datetime) -> None:
        require_payload_keys(transaction, {"transferId", "actualGrams", "reason", "senderApproval"})
        payload = transaction.payload
        transfer = self._pending(payload["transferId"])
        if transfer.receiver != transaction.sender_public_key:
            raise ParticipantRuleError("Only the designated receiver can respond to this transfer.")
        if when >= transfer.expires_at:
            raise ParticipantRuleError("This transfer has expired and can no longer be accepted.")
        actual = payload["actualGrams"]
        if type(actual) is not int or not 0 <= actual <= MAX_SAFE_INTEGER:
            raise ParticipantRuleError("The actual quantity must be a whole number of grams.")
        if actual > transfer.declared_grams:
            raise ParticipantRuleError("The actual quantity cannot exceed the declared quantity.")
        reason = payload["reason"]
        approval = payload["senderApproval"]
        if not isinstance(reason, str) or not isinstance(approval, str):
            raise ParticipantRuleError("The receipt payload has an unexpected structure.")
        if actual == transfer.declared_grams:
            if reason or approval:
                raise ParticipantRuleError("A reason or approval is only recorded for a discrepancy.")
            return
        require_text(reason, "discrepancy reason")
        if actual == 0:
            if not self._is_valid_loss_approval(transfer, reason, approval):
                raise ParticipantRuleError("A zero-quantity receipt requires the sender's approval signature.")
        elif approval:
            raise ParticipantRuleError("A sender approval is only used for a zero-quantity receipt.")

    @staticmethod
    def _is_valid_loss_approval(transfer: Transfer, reason: str, approval: str) -> bool:
        try:
            return verify_digest(transfer.sender, loss_approval_digest(transfer.transfer_id, reason), approval)
        except ValueError:
            return False

    def _check_transfer_reject(self, transaction: Transaction) -> None:
        require_payload_keys(transaction, {"transferId", "reason"})
        transfer = self._pending(transaction.payload["transferId"])
        if transfer.receiver != transaction.sender_public_key:
            raise ParticipantRuleError("Only the designated receiver can reject this transfer.")
        require_text(transaction.payload["reason"], "rejection reason")

    def _check_transfer_cancel(self, transaction: Transaction) -> None:
        require_payload_keys(transaction, {"transferId"})
        transfer = self._pending(transaction.payload["transferId"])
        if transfer.sender != transaction.sender_public_key:
            raise ParticipantRuleError("Only the original sender can cancel this transfer.")
