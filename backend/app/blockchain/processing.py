from dataclasses import dataclass
from datetime import datetime

from app.blockchain.business import (
    MAX_TEXT_LENGTH,
    MATERIAL_PROCESSOR_ROLE,
    RECYCLER_ROLE,
    BusinessLedger,
    require_grams,
    require_text,
)
from app.blockchain.participants import ParticipantLedger, ParticipantRuleError, require_payload_keys
from app.blockchain.structures import Transaction
from app.crypto.canonical import MAX_SAFE_INTEGER

PROCESS_TYPE = "processing.record"
CORRECTION_TYPE = "record.correct"
PROCESSING_TYPES = frozenset({PROCESS_TYPE, CORRECTION_TYPE})

MAX_OUTPUTS = 20


@dataclass(frozen=True)
class Material:
    material_id: str
    source_operation: str
    parent_item: str
    creator: str
    description: str
    quantity_grams: int
    created_at: datetime


@dataclass(frozen=True)
class Operation:
    operation_id: str
    processor: str
    input_item: str
    input_grams: int
    output_ids: tuple[str, ...]
    residual_grams: int
    method: str
    processed_at: datetime


@dataclass(frozen=True)
class Correction:
    correction_id: str
    target_id: str
    author: str
    explanation: str
    created_at: datetime


def material_id_for(operation_id: str, index: int) -> str:
    return f"{operation_id}-{index}"


class ProcessingLedger:
    def __init__(self, business: BusinessLedger, participants: ParticipantLedger) -> None:
        self._business = business
        self._participants = participants
        self._materials: dict[str, Material] = {}
        self._operations: dict[str, Operation] = {}
        self._corrections: dict[str, Correction] = {}

    def material(self, material_id: str) -> Material | None:
        return self._materials.get(material_id)

    def materials(self) -> tuple[Material, ...]:
        return tuple(self._materials.values())

    def operation(self, operation_id: str) -> Operation | None:
        return self._operations.get(operation_id)

    def operations(self) -> tuple[Operation, ...]:
        return tuple(self._operations.values())

    def operations_consuming(self, item_id: str) -> tuple[Operation, ...]:
        return tuple(operation for operation in self._operations.values() if operation.input_item == item_id)

    def corrections_for(self, target_id: str) -> tuple[Correction, ...]:
        return tuple(correction for correction in self._corrections.values() if correction.target_id == target_id)

    def check(self, transaction: Transaction) -> None:
        if transaction.tx_type == PROCESS_TYPE:
            self._check_process(transaction)
        elif transaction.tx_type == CORRECTION_TYPE:
            self._check_correction(transaction)

    def apply(self, transaction: Transaction, when: datetime) -> None:
        if transaction.tx_type == PROCESS_TYPE:
            self._apply_process(transaction, when)
        elif transaction.tx_type == CORRECTION_TYPE:
            payload = transaction.payload
            self._corrections[transaction.txid] = Correction(
                correction_id=transaction.txid,
                target_id=payload["targetId"],
                author=transaction.sender_public_key,
                explanation=payload["explanation"],
                created_at=when,
            )

    def _check_process(self, transaction: Transaction) -> None:
        require_payload_keys(transaction, {"inputItemId", "inputGrams", "outputs", "residualGrams", "method"})
        payload = transaction.payload
        processor = self._participants.participant(transaction.sender_public_key)
        if processor is None or processor.role not in (RECYCLER_ROLE, MATERIAL_PROCESSOR_ROLE):
            raise ParticipantRuleError("Only a registered Recycler or Material Processor can record processing.")
        if transaction.txid in self._operations:
            raise ParticipantRuleError("This processing operation has already been recorded.")

        input_item = payload["inputItemId"]
        if not isinstance(input_item, str):
            raise ParticipantRuleError("The input item does not exist on the accepted chain.")
        grams = require_grams(payload["inputGrams"], "input quantity")
        outputs = _check_outputs(payload["outputs"])
        residual = _check_residual(payload["residualGrams"])
        if sum(quantity for _, quantity in outputs) + residual != grams:
            raise ParticipantRuleError("The recovered outputs and residual must add up exactly to the input quantity.")
        method = payload["method"]
        if not isinstance(method, str) or len(method) > MAX_TEXT_LENGTH:
            raise ParticipantRuleError(f"The processing method must be at most {MAX_TEXT_LENGTH} characters.")

        if processor.role == RECYCLER_ROLE and self._business.batch(input_item) is None:
            raise ParticipantRuleError("A Recycler can only process an existing e-waste batch.")
        if processor.role == MATERIAL_PROCESSOR_ROLE and self._materials.get(input_item) is None:
            raise ParticipantRuleError("A Material Processor can only process recovered material.")
        if self._business.available(transaction.sender_public_key, input_item) < grams:
            raise ParticipantRuleError("The input quantity exceeds the available unreserved inventory.")

    def _apply_process(self, transaction: Transaction, when: datetime) -> None:
        payload = transaction.payload
        processor = transaction.sender_public_key
        input_item = payload["inputItemId"]
        grams = payload["inputGrams"]
        self._business.add_holding(processor, input_item, -grams)
        output_ids = []
        for index, (description, quantity) in enumerate(_check_outputs(payload["outputs"])):
            material_id = material_id_for(transaction.txid, index)
            self._business.register_material(material_id)
            self._materials[material_id] = Material(
                material_id=material_id,
                source_operation=transaction.txid,
                parent_item=input_item,
                creator=processor,
                description=description,
                quantity_grams=quantity,
                created_at=when,
            )
            self._business.add_holding(processor, material_id, quantity)
            output_ids.append(material_id)
        self._operations[transaction.txid] = Operation(
            operation_id=transaction.txid,
            processor=processor,
            input_item=input_item,
            input_grams=grams,
            output_ids=tuple(output_ids),
            residual_grams=payload["residualGrams"],
            method=payload["method"],
            processed_at=when,
        )

    def _check_correction(self, transaction: Transaction) -> None:
        require_payload_keys(transaction, {"targetId", "explanation"})
        payload = transaction.payload
        target_id = payload["targetId"]
        batch = self._business.batch(target_id) if isinstance(target_id, str) else None
        if isinstance(target_id, str) and target_id in self._operations:
            owner = self._operations[target_id].processor
        elif batch is not None:
            owner = batch.generator
        else:
            raise ParticipantRuleError("The correction must reference an existing batch or processing record.")
        if owner != transaction.sender_public_key:
            raise ParticipantRuleError("Only the wallet that created the original record can correct it.")
        require_text(payload["explanation"], "correction explanation")
        if transaction.txid in self._corrections:
            raise ParticipantRuleError("This correction has already been recorded.")


def _check_outputs(outputs: object) -> list[tuple[str, int]]:
    if not isinstance(outputs, list) or not 1 <= len(outputs) <= MAX_OUTPUTS:
        raise ParticipantRuleError(f"A processing record needs between 1 and {MAX_OUTPUTS} recovered outputs.")
    checked = []
    for output in outputs:
        if not isinstance(output, dict) or set(output) != {"description", "quantityGrams"}:
            raise ParticipantRuleError("Each recovered output needs a description and a quantity.")
        description = require_text(output["description"], "recovered material description")
        checked.append((description, require_grams(output["quantityGrams"], "recovered material quantity")))
    return checked


def _check_residual(value: object) -> int:
    if type(value) is not int or not 0 <= value <= MAX_SAFE_INTEGER:
        raise ParticipantRuleError("The residual quantity must be a whole number of grams, zero or more.")
    return value
