import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config.errors import ConfigurationError

MASTER_KEY_FILE_NAME = "master.key"
KEYRING_FILE_NAME = "keyring.jsonl"
RECORDS_FILE_NAME = "records.jsonl"
KEY_RETENTION = timedelta(hours=24)
_NONCE_BYTES = 12
_KEY_BYTES = 32


class ContactStoreError(ValueError):
    pass


def normalize_email(address: str) -> str:
    normalized = address.strip().lower()
    local, separator, domain = normalized.partition("@")
    if not local or not separator or "." not in domain or len(normalized) > 254:
        raise ContactStoreError("The email address is not valid.")
    return normalized


@dataclass(frozen=True)
class _KeyEntry:
    key_id: str
    wrapped_hex: str
    nonce_hex: str
    created_at: str
    status: str
    retired_at: str | None


def initialize_contact_store(directory: Path) -> None:
    if (directory / MASTER_KEY_FILE_NAME).exists():
        raise ConfigurationError("The contact store already exists and its master key is never replaced.")
    directory.mkdir(parents=True, exist_ok=True)
    master = secrets.token_bytes(_KEY_BYTES)
    descriptor = os.open(directory / MASTER_KEY_FILE_NAME, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(master.hex().encode("ascii"))
        handle.flush()
        os.fsync(handle.fileno())


class ContactStore:
    def __init__(self, directory: Path, *, clock=lambda: datetime.now(UTC)) -> None:
        master_path = directory / MASTER_KEY_FILE_NAME
        if not master_path.is_file():
            raise ConfigurationError("The contact store has no master key. Initialise it before use.")
        try:
            self._master = bytes.fromhex(master_path.read_text(encoding="ascii").strip())
        except ValueError as exc:
            raise ConfigurationError("The contact store master key could not be read.") from exc
        if len(self._master) != _KEY_BYTES:
            raise ConfigurationError("The contact store master key has an invalid length.")
        self._directory = directory
        self._clock = clock

    def add_contact(self, address: str, payload: dict[str, Any]) -> str:
        email = normalize_email(address)
        key_id, data_key = self._active_key()
        record_id = secrets.token_hex(16)
        nonce = secrets.token_bytes(_NONCE_BYTES)
        ciphertext = AESGCM(data_key).encrypt(nonce, _canonical(payload), record_id.encode("ascii"))
        self._append_line(
            RECORDS_FILE_NAME,
            {
                "record_id": record_id,
                "key_id": key_id,
                "lookup": self._lookup(email),
                "nonce": nonce.hex(),
                "ciphertext": ciphertext.hex(),
            },
        )
        return record_id

    def find_contacts(self, address: str) -> list[dict[str, Any]]:
        lookup = self._lookup(normalize_email(address))
        keys = self._keys_by_id()
        found: list[dict[str, Any]] = []
        for record in self._read_lines(RECORDS_FILE_NAME):
            if record["lookup"] != lookup or record["key_id"] not in keys:
                continue
            found.append(self._decrypt_record(record, keys[record["key_id"]]))
        return found

    def retire_active_key(self) -> None:
        entries = self._keyring()
        now = _timestamp(self._clock())
        updated = [
            _KeyEntry(e.key_id, e.wrapped_hex, e.nonce_hex, e.created_at, "retired", now)
            if e.status == "active"
            else e
            for e in entries
        ]
        self._write_keyring(updated)

    def purge_retired_keys(self) -> int:
        entries = self._keyring()
        cutoff = self._clock() - KEY_RETENTION
        kept = [
            e for e in entries
            if e.status == "active" or datetime.fromisoformat(e.retired_at or "") > cutoff
        ]
        removed = len(entries) - len(kept)
        if removed:
            self._write_keyring(kept)
        return removed

    def _active_key(self) -> tuple[str, bytes]:
        for entry in self._keyring():
            if entry.status == "active":
                return entry.key_id, self._unwrap(entry)
        key_id = secrets.token_hex(8)
        data_key = secrets.token_bytes(_KEY_BYTES)
        nonce = secrets.token_bytes(_NONCE_BYTES)
        wrapped = AESGCM(self._master).encrypt(nonce, data_key, key_id.encode("ascii"))
        entries = self._keyring()
        entries.append(
            _KeyEntry(key_id, wrapped.hex(), nonce.hex(), _timestamp(self._clock()), "active", None)
        )
        self._write_keyring(entries)
        return key_id, data_key

    def _keys_by_id(self) -> dict[str, bytes]:
        return {entry.key_id: self._unwrap(entry) for entry in self._keyring()}

    def _unwrap(self, entry: _KeyEntry) -> bytes:
        try:
            return AESGCM(self._master).decrypt(
                bytes.fromhex(entry.nonce_hex), bytes.fromhex(entry.wrapped_hex), entry.key_id.encode("ascii")
            )
        except (InvalidTag, ValueError) as exc:
            raise ContactStoreError("A contact data key could not be unwrapped.") from exc

    def _decrypt_record(self, record: dict[str, Any], data_key: bytes) -> dict[str, Any]:
        try:
            plaintext = AESGCM(data_key).decrypt(
                bytes.fromhex(record["nonce"]),
                bytes.fromhex(record["ciphertext"]),
                record["record_id"].encode("ascii"),
            )
        except (InvalidTag, ValueError) as exc:
            raise ContactStoreError("A contact record failed authentication.") from exc
        return json.loads(plaintext.decode("utf-8"))

    def _lookup(self, email: str) -> str:
        return hmac.new(self._master, b"contact-lookup-v1\n" + email.encode("utf-8"), hashlib.sha256).hexdigest()

    def _keyring(self) -> list[_KeyEntry]:
        return [
            _KeyEntry(
                key_id=line["key_id"],
                wrapped_hex=line["wrapped"],
                nonce_hex=line["nonce"],
                created_at=line["created_at"],
                status=line["status"],
                retired_at=line["retired_at"],
            )
            for line in self._read_lines(KEYRING_FILE_NAME)
        ]

    def _write_keyring(self, entries: list[_KeyEntry]) -> None:
        temporary = self._directory / f"{KEYRING_FILE_NAME}.tmp"
        with temporary.open("wb") as handle:
            for entry in entries:
                handle.write(
                    _canonical(
                        {
                            "key_id": entry.key_id,
                            "wrapped": entry.wrapped_hex,
                            "nonce": entry.nonce_hex,
                            "created_at": entry.created_at,
                            "status": entry.status,
                            "retired_at": entry.retired_at,
                        }
                    )
                    + b"\n"
                )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self._directory / KEYRING_FILE_NAME)

    def _append_line(self, name: str, record: dict[str, Any]) -> None:
        with (self._directory / name).open("ab") as handle:
            handle.write(_canonical(record) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _read_lines(self, name: str) -> list[dict[str, Any]]:
        path = self._directory / name
        if not path.is_file():
            return []
        records: list[dict[str, Any]] = []
        lines = path.read_bytes().split(b"\n")
        for index, raw in enumerate(lines):
            if not raw:
                continue
            try:
                records.append(json.loads(raw.decode("utf-8")))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                if index == len(lines) - 1 or all(not later for later in lines[index + 1 :]):
                    break
                raise ContactStoreError(f"The contact file '{name}' is damaged before its end.") from exc
        return records


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _timestamp(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()
