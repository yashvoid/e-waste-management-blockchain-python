import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from coincurve import PrivateKey
from coincurve.ecdsa import der_to_cdata, serialize_compact

from app.api.participants import WALLET_REQUEST_TAG, router
from app.crypto.canonical import canonical_bytes
from app.crypto.secp256k1 import domain_hash
from app.blockchain.participants import SUSPEND_TYPE
from app.node.attestation import PURPOSE_EMAIL_CHANGE, PURPOSE_REGISTRATION, attestation_from_dict, verify_attestation
from app.node.contact_store import ContactStore, initialize_contact_store
from app.node.email_delivery import SmtpSettings
from app.node.otp_service import OtpService
from app.node.pending_pool import PendingTransactionPool
from app.storage.chain_storage import open_chain_storage
from chain_helpers import key_for_label, mine
from test_participants import _block_time, _register, _tx, _wallet, network  # noqa: F401

ADDRESS = "alice@example.com"


def _smtp(sent: list, failing: dict):
    class RecordingSmtp:
        def __init__(self, host: str, port: int, timeout: float) -> None:
            if failing["on"]:
                raise ConnectionRefusedError("no route to the mail server")

        def __enter__(self):
            return self

        def __exit__(self, *exc_info: object) -> None:
            return None

        def starttls(self, context: object) -> None:
            return None

        def send_message(self, message: object) -> None:
            sent.append(message)

    return RecordingSmtp


@pytest.fixture
def api(tmp_path: Path, network):
    identities, config = network
    sent: list = []
    failing = {"on": False}
    app = FastAPI()
    app.include_router(router)
    with open_chain_storage(tmp_path / "chain", config) as storage:
        pool = PendingTransactionPool(storage)
        (tmp_path / "otp").mkdir()
        contacts = tmp_path / "contacts"
        initialize_contact_store(contacts)
        app.state.node_settings = SimpleNamespace(identity_dir=identities["node-a"].key_path.parent, node_id="node-a")
        app.state.shared_network = config
        app.state.chain_storage = storage
        app.state.transaction_relay = SimpleNamespace(submit_local=pool.admit)
        app.state.otp_service = OtpService(tmp_path / "otp")
        app.state.contact_store = ContactStore(contacts)
        app.state.smtp_settings = SmtpSettings(host="smtp.example.org", port=587, sender="codes@example.org")
        app.state.smtp_factory = _smtp(sent, failing)
        yield SimpleNamespace(client=TestClient(app), storage=storage, config=config, sent=sent, failing=failing)


def _code(api) -> str:
    return re.search(r"code is (\d{6})", api.sent[-1].get_content()).group(1)


def _request_registration_code(api, email: str = ADDRESS):
    return api.client.post("/api/participants/registration/codes", json={"email": email})


def _wallet_json(label: str) -> str:
    return _wallet(label)[1]


def test_registration_code_is_emailed_and_not_echoed(api) -> None:
    response = _request_registration_code(api)
    assert response.status_code == 200
    assert len(api.sent) == 1
    assert _code(api) not in response.text


def test_code_request_refused_when_email_is_not_configured(api) -> None:
    api.client.app.state.smtp_settings = None
    assert _request_registration_code(api).status_code == 503


def test_smtp_failure_is_reported_and_leaves_resend_available(api) -> None:
    api.failing["on"] = True
    response = _request_registration_code(api)
    assert response.status_code == 502
    api.failing["on"] = False
    assert _request_registration_code(api).status_code == 200


def test_resend_within_sixty_seconds_is_refused(api) -> None:
    assert _request_registration_code(api).status_code == 200
    assert _request_registration_code(api).status_code == 429


def test_full_registration_issues_attestation_that_verifies(api) -> None:
    _request_registration_code(api)
    wallet = _wallet_json("alice")
    response = api.client.post(
        "/api/participants/registration/attestations",
        json={"email": ADDRESS, "code": _code(api), "walletPublicKey": wallet, "role": "Recycler"},
    )
    assert response.status_code == 200
    attestation = attestation_from_dict(response.json()["attestation"])
    verify_attestation(attestation, config=api.config, expected_purpose=PURPOSE_REGISTRATION, chain_height=0)
    assert attestation.role == "Recycler" and attestation.wallet_public_key == wallet


def test_wrong_code_is_refused_and_five_failures_lock_the_code(api) -> None:
    _request_registration_code(api)
    real = _code(api)
    wrong = "000000" if real != "000000" else "111111"
    body = {"email": ADDRESS, "code": wrong, "walletPublicKey": _wallet_json("alice"), "role": "Generator"}
    for _ in range(5):
        assert api.client.post("/api/participants/registration/attestations", json=body).status_code == 400
    assert api.client.post("/api/participants/registration/attestations", json={**body, "code": real}).status_code == 400


def test_registration_rejects_unknown_role_and_malformed_wallet(api) -> None:
    _request_registration_code(api)
    base = {"email": ADDRESS, "code": _code(api)}
    unknown_role = api.client.post(
        "/api/participants/registration/attestations",
        json={**base, "walletPublicKey": _wallet_json("alice"), "role": "Auditor"},
    )
    bad_wallet = api.client.post(
        "/api/participants/registration/attestations",
        json={**base, "walletPublicKey": "not-a-key", "role": "Generator"},
    )
    assert unknown_role.status_code == 422
    assert bad_wallet.status_code == 422


def test_registered_wallet_cannot_request_another_registration(api) -> None:
    api.storage.add_block(mine(api.config, api.storage.store.tip, [_register(_network_of(api), "alice")], _block_time(1)))
    _request_registration_code(api)
    response = api.client.post(
        "/api/participants/registration/attestations",
        json={"email": ADDRESS, "code": _code(api), "walletPublicKey": _wallet_json("alice"), "role": "Generator"},
    )
    assert response.status_code == 409


def test_participant_state_is_read_from_the_canonical_chain(api) -> None:
    api.storage.add_block(mine(api.config, api.storage.store.tip, [_register(_network_of(api), "alice", role="Collector")], _block_time(1)))
    response = api.client.get(f"/api/participants/{_wallet_json('alice')}")
    assert response.status_code == 200
    assert response.json()["role"] == "Collector"
    assert api.client.get(f"/api/participants/{_wallet_json('bob')}").status_code == 404


def test_email_change_requires_registered_non_suspended_wallet(api) -> None:
    body = {**_signed_body("alice", ADDRESS, PURPOSE_EMAIL_CHANGE), "code": "123456"}
    assert api.client.post("/api/participants/email-change/attestations", json=body).status_code == 404
    network_fixture = _network_of(api)
    api.storage.add_block(mine(api.config, api.storage.store.tip, [_register(network_fixture, "alice")], _block_time(1)))
    api.storage.add_block(mine(api.config, api.storage.store.tip, [_tx(api.config, "alice", SUSPEND_TYPE, {}, nonce=1)], _block_time(2)))
    assert api.client.post("/api/participants/email-change/attestations", json=body).status_code == 403


def test_email_change_attestation_carries_the_registered_role(api) -> None:
    network_fixture = _network_of(api)
    api.storage.add_block(mine(api.config, api.storage.store.tip, [_register(network_fixture, "alice", role="Transporter")], _block_time(1)))
    api.client.post("/api/participants/email-change/codes", json=_signed_body("alice", ADDRESS, PURPOSE_EMAIL_CHANGE))
    response = api.client.post(
        "/api/participants/email-change/attestations",
        json={**_signed_body("alice", ADDRESS, PURPOSE_EMAIL_CHANGE), "code": _code(api)},
    )
    assert response.status_code == 200
    assert response.json()["attestation"]["role"] == "Transporter"
    assert response.json()["attestation"]["purpose"] == "email-change"


def test_registration_code_cannot_be_used_for_email_change(api) -> None:
    network_fixture = _network_of(api)
    api.storage.add_block(mine(api.config, api.storage.store.tip, [_register(network_fixture, "alice")], _block_time(1)))
    _request_registration_code(api)
    response = api.client.post(
        "/api/participants/email-change/attestations",
        json={**_signed_body("alice", ADDRESS, PURPOSE_EMAIL_CHANGE), "code": _code(api)},
    )
    assert response.status_code == 400


def test_transaction_submission_accepts_valid_and_rejects_forged(api) -> None:
    valid = _tx(api.config, "alice", "waste.record", {"x": 1})
    accepted = api.client.post("/api/participants/transactions", json={"transaction": valid.to_dict()})
    assert accepted.status_code == 200
    assert accepted.json()["state"] == "accepted"

    tampered = _tx(api.config, "alice", "waste.record", {"x": 2})
    forged = {**tampered.to_dict(), "signature": valid.signature}
    rejected = api.client.post("/api/participants/transactions", json={"transaction": forged})
    assert rejected.status_code == 422


def test_transaction_submission_rejects_malformed_structure(api) -> None:
    response = api.client.post("/api/participants/transactions", json={"transaction": {"type": "x"}})
    assert response.status_code == 422


def _signed_body(label: str, email: str, purpose: str, *, signer: str | None = None, issued_at: str | None = None) -> dict:
    issued = issued_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    wallet = _wallet_json(label)
    digest = domain_hash(
        WALLET_REQUEST_TAG,
        canonical_bytes({"purpose": purpose, "walletPublicKey": wallet, "email": email, "issuedAt": issued}),
    )
    signature = serialize_compact(der_to_cdata(PrivateKey(key_for_label(signer or label)).sign(digest, hasher=None))).hex()
    return {"email": email, "walletPublicKey": wallet, "issuedAt": issued, "signature": signature}


def test_email_change_code_requires_signature_from_the_wallet(api) -> None:
    forged = _signed_body("alice", ADDRESS, PURPOSE_EMAIL_CHANGE, signer="bob")
    assert api.client.post("/api/participants/email-change/codes", json=forged).status_code == 401
    assert api.sent == []
    valid = _signed_body("alice", ADDRESS, PURPOSE_EMAIL_CHANGE)
    assert api.client.post("/api/participants/email-change/codes", json=valid).status_code == 200


def test_signature_is_bound_to_the_new_address(api) -> None:
    body = _signed_body("alice", "mallory@example.com", PURPOSE_EMAIL_CHANGE)
    body["email"] = "victim-new@example.com"
    assert api.client.post("/api/participants/email-change/codes", json=body).status_code == 401
    assert api.sent == []


def test_signature_is_bound_to_the_purpose(api) -> None:
    body = _signed_body("alice", ADDRESS, PURPOSE_REGISTRATION)
    assert api.client.post("/api/participants/email-change/codes", json=body).status_code == 401


def test_stale_signed_request_is_refused(api) -> None:
    old = (datetime.now(UTC) - timedelta(minutes=11)).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = _signed_body("alice", ADDRESS, PURPOSE_EMAIL_CHANGE, issued_at=old)
    assert api.client.post("/api/participants/email-change/codes", json=body).status_code == 401


def test_code_for_email_change_is_sent_to_the_new_address(api) -> None:
    body = _signed_body("alice", ADDRESS, PURPOSE_EMAIL_CHANGE)
    assert api.client.post("/api/participants/email-change/codes", json=body).status_code == 200
    assert ADDRESS in str(api.sent[-1]["To"])


def test_email_change_attestation_requires_signature_from_registered_wallet(api) -> None:
    network_fixture = _network_of(api)
    api.storage.add_block(mine(api.config, api.storage.store.tip, [_register(network_fixture, "alice")], _block_time(1)))
    api.client.post("/api/participants/email-change/codes", json=_signed_body("alice", ADDRESS, PURPOSE_EMAIL_CHANGE))
    forged = {**_signed_body("alice", ADDRESS, PURPOSE_EMAIL_CHANGE, signer="bob"), "code": _code(api)}
    response = api.client.post("/api/participants/email-change/attestations", json=forged)
    assert response.status_code == 401


def test_email_change_code_cannot_produce_a_second_attestation(api) -> None:
    network_fixture = _network_of(api)
    api.storage.add_block(mine(api.config, api.storage.store.tip, [_register(network_fixture, "alice")], _block_time(1)))
    api.client.post("/api/participants/email-change/codes", json=_signed_body("alice", ADDRESS, PURPOSE_EMAIL_CHANGE))
    body = {**_signed_body("alice", ADDRESS, PURPOSE_EMAIL_CHANGE), "code": _code(api)}
    assert api.client.post("/api/participants/email-change/attestations", json=body).status_code == 200
    replay = {**_signed_body("alice", ADDRESS, PURPOSE_EMAIL_CHANGE), "code": _code(api)}
    assert api.client.post("/api/participants/email-change/attestations", json=replay).status_code == 400


def _network_of(api):
    return (
        {"node-a": SimpleNamespace(key_path=api.client.app.state.node_settings.identity_dir / "placeholder")},
        api.config,
    )
