import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from app.config.errors import ConfigurationError
from app.config.shared_network import TrustedNode, TrustEpoch
from app.node.identity import (
    CERTIFICATE_FILE_NAME,
    IDENTITY_FILE_NAME,
    KEY_FILE_NAME,
    create_node_identity,
    load_node_identity,
)
from app.node.peer_trust import (
    accepted_certificate_paths,
    import_peer_certificate,
    require_listed_identity,
    trusted_peer_certificates,
)
from chain_helpers import attestation_key_hex
from node_helpers import create_identities, network_config


def test_each_node_gets_its_own_identity(tmp_path: Path) -> None:
    identities = create_identities(tmp_path, ["node-a", "node-b"])
    assert identities["node-a"].node_id != identities["node-b"].node_id
    assert identities["node-a"].certificate_sha256 != identities["node-b"].certificate_sha256
    assert (tmp_path / "identities/node-a" / KEY_FILE_NAME).read_bytes() != (
        tmp_path / "identities/node-b" / KEY_FILE_NAME
    ).read_bytes()


def test_restart_loads_the_same_identity_without_regenerating(tmp_path: Path) -> None:
    identity_dir = tmp_path / "identity"
    created = create_node_identity(identity_dir, "node-a")
    key_before = (identity_dir / KEY_FILE_NAME).read_bytes()

    reloaded = load_node_identity(identity_dir)

    assert reloaded == created
    assert (identity_dir / KEY_FILE_NAME).read_bytes() == key_before
    with pytest.raises(ConfigurationError, match="never replaced"):
        create_node_identity(identity_dir, "node-a")


def test_missing_identity_is_never_created_automatically(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="never created automatically"):
        load_node_identity(tmp_path / "empty")
    assert not (tmp_path / "empty").exists()


def test_identity_with_mismatched_key_is_rejected(tmp_path: Path) -> None:
    identities = create_identities(tmp_path, ["node-a", "node-b"])
    other_key = (tmp_path / "identities/node-b" / KEY_FILE_NAME).read_bytes()
    (tmp_path / "identities/node-a" / KEY_FILE_NAME).write_bytes(other_key)

    with pytest.raises(ConfigurationError, match="does not match the node certificate"):
        load_node_identity(identities["node-a"].key_path.parent)


def test_identity_record_with_wrong_fingerprint_is_rejected(tmp_path: Path) -> None:
    identities = create_identities(tmp_path, ["node-a"])
    record_path = tmp_path / "identities/node-a" / IDENTITY_FILE_NAME
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["certificate_sha256"] = "0" * 64
    record_path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(ConfigurationError, match="fingerprint in the identity record"):
        load_node_identity(identities["node-a"].key_path.parent)


def test_identity_with_missing_certificate_is_rejected(tmp_path: Path) -> None:
    identities = create_identities(tmp_path, ["node-a"])
    (tmp_path / "identities/node-a" / CERTIFICATE_FILE_NAME).unlink()

    with pytest.raises(ConfigurationError, match="No complete node identity"):
        load_node_identity(identities["node-a"].key_path.parent)


@pytest.mark.skipif(os.name != "posix", reason="File permission bits apply on POSIX systems only")
def test_private_key_is_owner_readable_only(tmp_path: Path) -> None:
    identity = create_node_identity(tmp_path / "identity", "node-a")
    assert identity.key_path.stat().st_mode & 0o777 == 0o600


def test_unlisted_identity_is_refused_at_startup(tmp_path: Path) -> None:
    identities = create_identities(tmp_path, ["node-a", "node-b"])
    config = network_config({"node-b": identities["node-b"]})

    with pytest.raises(ConfigurationError, match="not listed"):
        require_listed_identity(identities["node-a"], config)


def test_peer_certificate_import_requires_listed_fingerprint(tmp_path: Path) -> None:
    identities = create_identities(tmp_path, ["node-a", "node-b"])
    config = network_config({"node-a": identities["node-a"]})
    outsider = create_node_identity(tmp_path / "outsider", "node-x")

    with pytest.raises(ConfigurationError, match="not listed"):
        import_peer_certificate(identities["node-a"].key_path.parent, config, outsider.certificate_path)
    assert trusted_peer_certificates(identities["node-a"].key_path.parent, config, "node-a") == {}


def test_own_certificate_is_not_imported_as_a_peer(tmp_path: Path) -> None:
    identities = create_identities(tmp_path, ["node-a"])
    config = network_config(identities)

    with pytest.raises(ConfigurationError, match="own certificate"):
        import_peer_certificate(identities["node-a"].key_path.parent, config, identities["node-a"].certificate_path)


def test_import_stores_listed_peer_and_refuses_replacement(tmp_path: Path) -> None:
    identities = create_identities(tmp_path, ["node-a", "node-b"])
    config = network_config(identities)
    identity_dir = identities["node-a"].key_path.parent

    assert import_peer_certificate(identity_dir, config, identities["node-b"].certificate_path) == "node-b"
    assert set(trusted_peer_certificates(identity_dir, config, "node-a")) == {"node-b"}
    assert import_peer_certificate(identity_dir, config, identities["node-b"].certificate_path) == "node-b"

    renewed = create_node_identity(tmp_path / "renewed", "node-b")
    renewal_nodes = (
        TrustedNode("node-a", identities["node-a"].certificate_sha256, attestation_key_hex("node-a"), "active"),
        TrustedNode("node-b", identities["node-b"].certificate_sha256, attestation_key_hex("node-b"), "retired"),
        TrustedNode("node-b", renewed.certificate_sha256, attestation_key_hex("node-b-renewed"), "active"),
    )
    renewal = replace(config, trust_epochs=(config.trust_epochs[0], TrustEpoch(1, 20, renewal_nodes)))
    assert import_peer_certificate(identity_dir, renewal, renewed.certificate_path) == "node-b"
    assert trusted_peer_certificates(identity_dir, renewal, "node-a")["node-b"].is_file()
    assert len(accepted_certificate_paths(identity_dir, renewal, "node-a")) == 2

    unlisted = create_node_identity(tmp_path / "unlisted", "node-b")
    with pytest.raises(ConfigurationError, match="not listed"):
        import_peer_certificate(identity_dir, renewal, unlisted.certificate_path)
