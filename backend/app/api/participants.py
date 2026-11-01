import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.blockchain.participants import ROLES, Participant, ParticipantLedger
from app.crypto.canonical import canonical_bytes
from app.crypto.secp256k1 import domain_hash, parse_compressed_public_key, verify_digest
from app.node.attestation import PURPOSE_EMAIL_CHANGE, PURPOSE_REGISTRATION, issue_attestation
from app.node.contact_store import ContactStoreError, normalize_email
from app.node.email_delivery import EmailDeliveryError, SmtpSettings, send_verification_code
from app.node.otp_service import OtpError, OtpRateLimited
from app.storage.block_records import decode_transaction_object
from app.storage.errors import StorageError

router = APIRouter(prefix="/api/participants", tags=["participants"])

WALLET_REQUEST_TAG = "EWASTE-PARTICIPANT-REQUEST-V1"
WALLET_REQUEST_MAX_AGE = timedelta(minutes=10)


class EmailRequest(BaseModel):
    email: str = Field(max_length=254)


class RegistrationRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    email: str = Field(max_length=254)
    code: str = Field(pattern=r"^[0-9]{6}$")
    wallet_public_key: str = Field(alias="walletPublicKey", max_length=66)
    role: str = Field(max_length=64)


class SignedEmailChangeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    email: str = Field(max_length=254)
    wallet_public_key: str = Field(alias="walletPublicKey", max_length=66)
    issued_at: str = Field(alias="issuedAt", max_length=20)
    signature: str = Field(max_length=128)


class EmailChangeAttestationRequest(SignedEmailChangeRequest):
    code: str = Field(pattern=r"^[0-9]{6}$")


class TransactionRequest(BaseModel):
    transaction: dict[str, Any]


def _address(email: str) -> str:
    try:
        return normalize_email(email)
    except ContactStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _wallet(text: str) -> str:
    try:
        parse_compressed_public_key(text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="The wallet public key is not valid.") from exc
    return text


def _ledger(request: Request) -> ParticipantLedger:
    storage = request.app.state.chain_storage
    with storage.lock:
        return ParticipantLedger.from_blocks(storage.store.canonical_chain, storage.config)


def _send_code(request: Request, purpose: str, email: str) -> dict[str, str]:
    smtp: SmtpSettings | None = request.app.state.smtp_settings
    if smtp is None:
        raise HTTPException(status_code=503, detail="Email delivery is not configured on this node.")
    address = _address(email)
    try:
        request.app.state.otp_service.request_code(
            f"{purpose}|{address}",
            lambda code: send_verification_code(
                smtp, address, code, smtp_factory=request.app.state.smtp_factory
            ),
        )
    except OtpRateLimited as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except EmailDeliveryError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"status": "sent"}


def _check_code(request: Request, purpose: str, email: str, code: str) -> None:
    try:
        verified = request.app.state.otp_service.verify_code(f"{purpose}|{_address(email)}", code)
    except OtpError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not verified:
        raise HTTPException(status_code=400, detail="The code is incorrect.")


def _issue(request: Request, purpose: str, email: str, wallet: str, role: str) -> dict[str, Any]:
    settings = request.app.state.node_settings
    config = request.app.state.shared_network
    request.app.state.contact_store.add_contact(
        _address(email), {"purpose": purpose, "walletPublicKey": wallet, "role": role}
    )
    attestation = issue_attestation(
        settings.identity_dir,
        config,
        node_id=settings.node_id,
        purpose=purpose,
        wallet_public_key=wallet,
        role=role,
        request_id=secrets.token_hex(16),
        nonce=secrets.token_hex(16),
        issued_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    return {"attestation": attestation.to_dict()}


def _participant_view(participant: Participant) -> dict[str, Any]:
    return {
        "walletPublicKey": participant.wallet_public_key,
        "role": participant.role,
        "registeredAt": participant.registered_at,
        "emailVersion": participant.email_version,
        "suspended": participant.suspended,
    }


@router.post("/registration/codes")
def registration_code(body: EmailRequest, request: Request) -> dict[str, str]:
    return _send_code(request, PURPOSE_REGISTRATION, body.email)


@router.post("/registration/attestations")
def registration_attestation(body: RegistrationRequest, request: Request) -> dict[str, Any]:
    wallet = _wallet(body.wallet_public_key)
    if body.role not in ROLES:
        raise HTTPException(status_code=422, detail="The requested business role is not recognised.")
    if _ledger(request).participant(wallet) is not None:
        raise HTTPException(status_code=409, detail="This wallet is already registered.")
    _check_code(request, PURPOSE_REGISTRATION, body.email, body.code)
    return _issue(request, PURPOSE_REGISTRATION, body.email, wallet, body.role)


def _require_wallet_signature(body: SignedEmailChangeRequest, purpose: str) -> str:
    wallet = _wallet(body.wallet_public_key)
    address = _address(body.email)
    try:
        issued = datetime.strptime(body.issued_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="The request time is not valid.") from exc
    age = datetime.now(UTC) - issued
    if age > WALLET_REQUEST_MAX_AGE or age < -WALLET_REQUEST_MAX_AGE:
        raise HTTPException(status_code=401, detail="The signed request has expired. Try again.")
    digest = domain_hash(
        WALLET_REQUEST_TAG,
        canonical_bytes(
            {"purpose": purpose, "walletPublicKey": wallet, "email": address, "issuedAt": body.issued_at}
        ),
    )
    if not verify_digest(wallet, digest, body.signature):
        raise HTTPException(status_code=401, detail="The wallet signature is not valid.")
    return wallet


@router.post("/email-change/codes")
def email_change_code(body: SignedEmailChangeRequest, request: Request) -> dict[str, str]:
    _require_wallet_signature(body, PURPOSE_EMAIL_CHANGE)
    return _send_code(request, PURPOSE_EMAIL_CHANGE, body.email)


@router.post("/email-change/attestations")
def email_change_attestation(body: EmailChangeAttestationRequest, request: Request) -> dict[str, Any]:
    wallet = _require_wallet_signature(body, PURPOSE_EMAIL_CHANGE)
    participant = _ledger(request).participant(wallet)
    if participant is None:
        raise HTTPException(status_code=404, detail="This wallet is not registered.")
    if participant.suspended:
        raise HTTPException(status_code=403, detail="This wallet is suspended.")
    _check_code(request, PURPOSE_EMAIL_CHANGE, body.email, body.code)
    return _issue(request, PURPOSE_EMAIL_CHANGE, body.email, wallet, participant.role)


@router.post("/transactions")
def submit_transaction(body: TransactionRequest, request: Request) -> dict[str, str]:
    try:
        transaction = decode_transaction_object(body.transaction)
    except StorageError as exc:
        raise HTTPException(status_code=422, detail="The transaction has an invalid structure.") from exc
    result = request.app.state.transaction_relay.submit_local(transaction)
    if result.state == "rejected":
        raise HTTPException(status_code=422, detail=result.detail)
    if result.state == "unavailable":
        raise HTTPException(status_code=503, detail=result.detail)
    return {"state": result.state, "detail": result.detail, "txid": transaction.txid}


@router.get("/{wallet_public_key}")
def participant_state(wallet_public_key: str, request: Request) -> dict[str, Any]:
    participant = _ledger(request).participant(_wallet(wallet_public_key))
    if participant is None:
        raise HTTPException(status_code=404, detail="This wallet is not registered.")
    return _participant_view(participant)
