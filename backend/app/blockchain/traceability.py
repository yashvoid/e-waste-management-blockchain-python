from dataclasses import dataclass

from app.blockchain.business import ACCEPTED, PENDING
from app.blockchain.ledger import ChainLedger


@dataclass(frozen=True)
class CompletionStatus:
    item_id: str
    quantity_grams: int
    remaining_grams: int
    processed_grams: int
    residual_grams: int
    discrepancy_grams: int
    pending_grams: int
    completed: bool


@dataclass(frozen=True)
class LineageEntry:
    kind: str
    record_id: str
    participants: tuple[str, ...]
    quantity_grams: int | None


def batch_status(ledger: ChainLedger, batch_id: str) -> CompletionStatus | None:
    batch = ledger.business.batch(batch_id)
    if batch is None:
        return None
    remaining = ledger.business.total_held(batch_id)
    pending = _pending_grams(ledger, batch_id)
    return CompletionStatus(
        item_id=batch_id,
        quantity_grams=batch.quantity_grams,
        remaining_grams=remaining,
        processed_grams=_processed(ledger, batch_id),
        residual_grams=_residual(ledger, batch_id),
        discrepancy_grams=ledger.business.discrepancy(batch_id),
        pending_grams=pending,
        completed=remaining == 0 and pending == 0,
    )


def material_status(ledger: ChainLedger, material_id: str) -> CompletionStatus | None:
    material = ledger.processing.material(material_id)
    if material is None:
        return None
    remaining = ledger.business.total_held(material_id)
    pending = _pending_grams(ledger, material_id)
    return CompletionStatus(
        item_id=material_id,
        quantity_grams=material.quantity_grams,
        remaining_grams=remaining,
        processed_grams=_processed(ledger, material_id),
        residual_grams=_residual(ledger, material_id),
        discrepancy_grams=ledger.business.discrepancy(material_id),
        pending_grams=pending,
        completed=remaining == 0 and pending == 0,
    )


def lineage(ledger: ChainLedger, item_id: str) -> tuple[LineageEntry, ...]:
    origin, items, operations = _chain(ledger, item_id)
    if origin is None:
        return ()
    entries = []
    for index, item in enumerate(items):
        if index == 0:
            batch = ledger.business.batch(item)
            entries.append(LineageEntry("batch", batch.batch_id, (batch.generator,), batch.quantity_grams))
        entries.extend(
            LineageEntry("transfer", transfer.transfer_id, (transfer.sender, transfer.receiver), transfer.actual_grams)
            for transfer in ledger.business.transfers()
            if transfer.batch_id == item and transfer.status == ACCEPTED
        )
        if index < len(operations):
            operation = operations[index]
            entries.append(
                LineageEntry("processing", operation.operation_id, (operation.processor,), operation.input_grams)
            )

    with_corrections = []
    for entry in entries:
        with_corrections.append(entry)
        with_corrections.extend(
            LineageEntry("correction", correction.correction_id, (correction.author,), None)
            for correction in ledger.processing.corrections_for(entry.record_id)
        )
    return tuple(with_corrections)


def involved_wallets(ledger: ChainLedger, item_id: str) -> frozenset[str]:
    origin, items, _ = _chain(ledger, item_id)
    if origin is None:
        return frozenset()
    wallets = {wallet for entry in lineage(ledger, item_id) for wallet in entry.participants}
    for transfer in ledger.business.transfers():
        if transfer.batch_id in items:
            wallets.update((transfer.sender, transfer.receiver))
    return frozenset(wallets)


def can_view_history(ledger: ChainLedger, viewer_public_key: str, item_id: str) -> bool:
    return viewer_public_key in involved_wallets(ledger, item_id)


def _chain(ledger: ChainLedger, item_id: str):
    steps = []
    current = item_id
    while (material := ledger.processing.material(current)) is not None:
        operation = ledger.processing.operation(material.source_operation)
        steps.append((operation, current))
        current = operation.input_item
    steps.reverse()
    if ledger.business.batch(current) is None:
        return None, (), ()
    items = (current, *(produced for _, produced in steps))
    operations = tuple(operation for operation, _ in steps)
    return current, items, operations


def _pending_grams(ledger: ChainLedger, item_id: str) -> int:
    return sum(
        transfer.declared_grams
        for transfer in ledger.business.transfers()
        if transfer.batch_id == item_id and transfer.status == PENDING
    )


def _processed(ledger: ChainLedger, item_id: str) -> int:
    return sum(operation.input_grams for operation in ledger.processing.operations_consuming(item_id))


def _residual(ledger: ChainLedger, item_id: str) -> int:
    return sum(operation.residual_grams for operation in ledger.processing.operations_consuming(item_id))
