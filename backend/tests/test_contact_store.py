import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.config.errors import ConfigurationError
from app.storage.backup import export_backup
from chain_helpers import shared_network_config
from app.node.contact_store import (
    KEY_RETENTION,
    KEYRING_FILE_NAME,
    MASTER_KEY_FILE_NAME,
    RECORDS_FILE_NAME,
    ContactStore,
    ContactStoreError,
    initialize_contact_store,
    normalize_email,
)

START = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)


class Clock:
    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment


@pytest.fixture
def store_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "contacts"
    initialize_contact_store(directory)
    return directory


def _store(directory: Path, clock: Clock) -> ContactStore:
    return ContactStore(directory, clock=clock)


def test_contact_round_trips_and_lookup_is_case_insensitive(store_dir: Path) -> None:
    clock = Clock(START)
    store = _store(store_dir, clock)
    store.add_contact("Alice@Example.com ", {"wallet": "02" + "11" * 32})

    found = _store(store_dir, clock).find_contacts("alice@example.COM")
    assert found == [{"wallet": "02" + "11" * 32}]
    assert _store(store_dir, clock).find_contacts("bob@example.com") == []


def test_stored_records_do_not_contain_plaintext_email(store_dir: Path) -> None:
    _store(store_dir, Clock(START)).add_contact("alice@example.com", {"wallet": "wallet-x"})
    stored = (store_dir / RECORDS_FILE_NAME).read_text(encoding="utf-8") + (store_dir / KEYRING_FILE_NAME).read_text(
        encoding="utf-8"
    )
    assert "alice@example.com" not in stored
    assert "wallet-x" not in stored


def test_initialisation_never_replaces_existing_master_key(store_dir: Path) -> None:
    before = (store_dir / MASTER_KEY_FILE_NAME).read_bytes()
    with pytest.raises(ConfigurationError, match="never replaced"):
        initialize_contact_store(store_dir)
    assert (store_dir / MASTER_KEY_FILE_NAME).read_bytes() == before


def test_store_without_master_key_is_refused(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    with pytest.raises(ConfigurationError, match="no master key"):
        ContactStore(tmp_path / "empty")


def test_wrong_master_key_cannot_read_contacts(store_dir: Path) -> None:
    clock = Clock(START)
    _store(store_dir, clock).add_contact("alice@example.com", {"wallet": "w"})
    (store_dir / MASTER_KEY_FILE_NAME).write_text("00" * 32, encoding="ascii")
    with pytest.raises(ContactStoreError):
        _store(store_dir, clock).find_contacts("alice@example.com")


def test_tampered_record_fails_authentication(store_dir: Path) -> None:
    clock = Clock(START)
    _store(store_dir, clock).add_contact("alice@example.com", {"wallet": "w"})
    path = store_dir / RECORDS_FILE_NAME
    record = json.loads(path.read_text(encoding="utf-8"))
    record["ciphertext"] = ("00" if record["ciphertext"][:2] != "00" else "11") + record["ciphertext"][2:]
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    with pytest.raises(ContactStoreError, match="authentication"):
        _store(store_dir, clock).find_contacts("alice@example.com")


def test_truncated_final_record_is_ignored_on_recovery(store_dir: Path) -> None:
    clock = Clock(START)
    store = _store(store_dir, clock)
    store.add_contact("alice@example.com", {"wallet": "w1"})
    with (store_dir / RECORDS_FILE_NAME).open("ab") as handle:
        handle.write(b'{"record_id": "partial')
    assert _store(store_dir, clock).find_contacts("alice@example.com") == [{"wallet": "w1"}]


def test_damage_before_the_end_of_records_is_reported(store_dir: Path) -> None:
    clock = Clock(START)
    store = _store(store_dir, clock)
    store.add_contact("alice@example.com", {"wallet": "w1"})
    with (store_dir / RECORDS_FILE_NAME).open("ab") as handle:
        handle.write(b"garbage\n")
    store.add_contact("bob@example.com", {"wallet": "w2"})
    with pytest.raises(ContactStoreError, match="damaged"):
        _store(store_dir, clock).find_contacts("alice@example.com")


def test_retired_key_keeps_contacts_readable_until_retention_ends(store_dir: Path) -> None:
    clock = Clock(START)
    store = _store(store_dir, clock)
    store.add_contact("alice@example.com", {"wallet": "w"})
    store.retire_active_key()

    clock.moment = START + KEY_RETENTION - timedelta(minutes=1)
    assert store.purge_retired_keys() == 0
    assert _store(store_dir, clock).find_contacts("alice@example.com") == [{"wallet": "w"}]


def test_purge_after_retention_makes_contacts_unreadable(store_dir: Path) -> None:
    clock = Clock(START)
    store = _store(store_dir, clock)
    store.add_contact("alice@example.com", {"wallet": "w"})
    store.retire_active_key()

    clock.moment = START + KEY_RETENTION + timedelta(minutes=1)
    assert store.purge_retired_keys() == 1
    assert _store(store_dir, clock).find_contacts("alice@example.com") == []
    assert "alice" not in (store_dir / KEYRING_FILE_NAME).read_text(encoding="utf-8")


def test_new_contacts_use_a_fresh_key_after_rotation(store_dir: Path) -> None:
    clock = Clock(START)
    store = _store(store_dir, clock)
    store.add_contact("alice@example.com", {"wallet": "w1"})
    store.retire_active_key()
    store.add_contact("bob@example.com", {"wallet": "w2"})

    clock.moment = START + KEY_RETENTION + timedelta(minutes=1)
    store.purge_retired_keys()
    assert _store(store_dir, clock).find_contacts("alice@example.com") == []
    assert _store(store_dir, clock).find_contacts("bob@example.com") == [{"wallet": "w2"}]


def test_missing_keyring_makes_existing_records_unreadable(store_dir: Path) -> None:
    clock = Clock(START)
    _store(store_dir, clock).add_contact("alice@example.com", {"wallet": "w"})
    (store_dir / KEYRING_FILE_NAME).unlink()
    assert _store(store_dir, clock).find_contacts("alice@example.com") == []


@pytest.mark.parametrize("address", ["", "no-at-sign", "@example.com", "a@nodot", "a" * 250 + "@x.com"])
def test_invalid_email_is_rejected(address: str) -> None:
    with pytest.raises(ContactStoreError):
        normalize_email(address)


def test_application_backup_contains_no_contact_material(tmp_path: Path) -> None:
    data_dir = tmp_path / "node-data"
    contacts_dir = data_dir / "contacts"
    initialize_contact_store(contacts_dir)
    clock = Clock(START)
    _store(contacts_dir, clock).add_contact("alice@example.com", {"wallet": "wallet-secret-marker"})
    master_hex = (contacts_dir / MASTER_KEY_FILE_NAME).read_text(encoding="ascii").strip()

    destination = tmp_path / "backup.jsonl"
    export_backup(data_dir, shared_network_config(), destination)

    exported = destination.read_text(encoding="utf-8")
    assert exported
    assert master_hex not in exported
    assert "alice@example.com" not in exported
    assert "wallet-secret-marker" not in exported
