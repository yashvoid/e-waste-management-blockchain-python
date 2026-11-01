from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from app.blockchain.structures import Block, Transaction, parse_utc_timestamp
from app.config.shared_network import SharedNetworkConfig
from app.node.attestation import (
    PURPOSE_EMAIL_CHANGE,
    PURPOSE_REGISTRATION,
    Attestation,
    AttestationError,
    attestation_from_dict,
    verify_attestation,
)

REGISTER_TYPE = "participant.register"
EMAIL_CHANGE_TYPE = "participant.email-change"
SUSPEND_TYPE = "participant.suspend"
PARTICIPANT_TYPES = frozenset({REGISTER_TYPE, EMAIL_CHANGE_TYPE, SUSPEND_TYPE})

ROLES = frozenset({"Generator", "Collector", "Transporter", "Recycler", "Material Processor"})
ATTESTATION_WINDOW = timedelta(hours=24)


class ParticipantRuleError(ValueError):
    pass


@dataclass(frozen=True)
class Participant:
    wallet_public_key: str
    role: str
    registered_at: str
    email_version: int
    suspended: bool


class ParticipantLedger:
    def __init__(self) -> None:
        self._participants: dict[str, Participant] = {}
        self._consumed: set[tuple[str, str, str]] = set()

    @classmethod
    def from_blocks(cls, blocks: Iterable[Block], config: SharedNetworkConfig) -> "ParticipantLedger":
        ledger = cls()
        for block in blocks:
            for transaction in block.transactions:
                ledger.apply(transaction, block_timestamp=block.timestamp, height=block.height, config=config)
        return ledger

    def participant(self, wallet_public_key: str) -> Participant | None:
        return self._participants.get(wallet_public_key)

    def participants(self) -> tuple[Participant, ...]:
        return tuple(self._participants.values())

    def check(
        self,
        transaction: Transaction,
        *,
        block_timestamp: str,
        height: int,
        config: SharedNetworkConfig,
    ) -> None:
        sender = self._participants.get(transaction.sender_public_key)
        if transaction.tx_type not in PARTICIPANT_TYPES:
            if sender is not None and sender.suspended:
                raise ParticipantRuleError("A suspended wallet cannot start new business transactions.")
            return
        if transaction.tx_type == SUSPEND_TYPE:
            require_payload_keys(transaction, set())
            if sender is None:
                raise ParticipantRuleError("Only a registered wallet can suspend itself.")
            if sender.suspended:
                raise ParticipantRuleError("This wallet is already suspended.")
            return

        attestation = _attestation_payload(transaction)
        when = parse_utc_timestamp(block_timestamp)
        _check_attestation_window(attestation, when)
        try:
            verify_attestation(
                attestation,
                config=config,
                expected_purpose=(
                    PURPOSE_REGISTRATION if transaction.tx_type == REGISTER_TYPE else PURPOSE_EMAIL_CHANGE
                ),
                chain_height=height,
            )
        except AttestationError as exc:
            raise ParticipantRuleError(str(exc)) from exc
        if attestation.wallet_public_key != transaction.sender_public_key:
            raise ParticipantRuleError("The attestation was issued for a different wallet.")
        if (attestation.issuer_node_id, attestation.request_id, attestation.nonce) in self._consumed:
            raise ParticipantRuleError("This attestation has already been used.")

        if transaction.tx_type == REGISTER_TYPE:
            if sender is not None:
                raise ParticipantRuleError("This wallet is already registered. A role cannot be changed.")
            if attestation.role not in ROLES:
                raise ParticipantRuleError("The requested business role is not recognised.")
            return

        if sender is None:
            raise ParticipantRuleError("Only a registered wallet can change its email address.")
        if sender.suspended:
            raise ParticipantRuleError("A suspended wallet cannot change its email address.")
        if attestation.role != sender.role:
            raise ParticipantRuleError("The attestation role does not match the registered role.")

    def apply(
        self,
        transaction: Transaction,
        *,
        block_timestamp: str,
        height: int,
        config: SharedNetworkConfig,
    ) -> None:
        self.check(transaction, block_timestamp=block_timestamp, height=height, config=config)
        key = transaction.sender_public_key
        if transaction.tx_type == SUSPEND_TYPE:
            self._participants[key] = replace(self._participants[key], suspended=True)
        elif transaction.tx_type == REGISTER_TYPE:
            attestation = _attestation_payload(transaction)
            self._consumed.add((attestation.issuer_node_id, attestation.request_id, attestation.nonce))
            self._participants[key] = Participant(
                wallet_public_key=key,
                role=attestation.role,
                registered_at=block_timestamp,
                email_version=1,
                suspended=False,
            )
        elif transaction.tx_type == EMAIL_CHANGE_TYPE:
            attestation = _attestation_payload(transaction)
            self._consumed.add((attestation.issuer_node_id, attestation.request_id, attestation.nonce))
            current = self._participants[key]
            self._participants[key] = replace(current, email_version=current.email_version + 1)


def _attestation_payload(transaction: Transaction) -> Attestation:
    require_payload_keys(transaction, {"attestation"})
    try:
        return attestation_from_dict(transaction.payload["attestation"])
    except AttestationError as exc:
        raise ParticipantRuleError(str(exc)) from exc


def require_payload_keys(transaction: Transaction, allowed: set[str]) -> None:
    if set(transaction.payload) != allowed:
        raise ParticipantRuleError("The participant transaction payload has an unexpected structure.")


def _check_attestation_window(attestation: Attestation, when: datetime) -> None:
    issued = parse_utc_timestamp(attestation.issued_at)
    if not issued <= when <= issued + ATTESTATION_WINDOW:
        raise ParticipantRuleError("The attestation is not within its 24-hour inclusion window.")
