import argparse
import getpass
import sys
from pathlib import Path

from app.config.errors import ConfigurationError
from app.config.node_settings import OPERATOR_VERIFIER_ENV
from app.config.shared_network import load_shared_network_config
from app.crypto.password_verifier import make_verifier
from app.node.attestation import attestation_public_key_hex, load_attestation_key
from app.node.identity import create_node_identity
from app.node.peer_trust import import_peer_certificate


def _read_new_operator_password() -> str:
    first = getpass.getpass("New operator password: ")
    second = getpass.getpass("Repeat the operator password: ")
    if first != second:
        raise ConfigurationError("The two passwords do not match.")
    return first


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.node.provision", description="Manage this node's identity.")
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create-identity", help="Create this node's key and certificate once.")
    create.add_argument("--identity-dir", type=Path, required=True)
    create.add_argument("--node-id", required=True)

    import_peer = commands.add_parser("import-peer", help="Add another node's public certificate after verifying it.")
    import_peer.add_argument("--identity-dir", type=Path, required=True)
    import_peer.add_argument("--shared-config", type=Path, required=True)
    import_peer.add_argument("--certificate", type=Path, required=True)

    commands.add_parser(
        "set-operator-password",
        help="Create the operator password verifier for this node's private configuration.",
    )

    args = parser.parse_args(argv)
    try:
        if args.command == "create-identity":
            identity = create_node_identity(args.identity_dir, args.node_id)
            print(f"Created identity for node '{identity.node_id}'.")
            print(f"Certificate SHA-256 fingerprint: {identity.certificate_sha256}")
            print(f"Share this certificate file only: {identity.certificate_path}")
            print(f"Attestation public key (list it in the trust epoch): {attestation_public_key_hex(load_attestation_key(args.identity_dir))}")
        elif args.command == "set-operator-password":
            verifier = make_verifier(_read_new_operator_password())
            print("Add this line to this node's private configuration, then restart the node:")
            print(f"{OPERATOR_VERIFIER_ENV}={verifier}")
        else:
            shared_config = load_shared_network_config(args.shared_config)
            node_id = import_peer_certificate(args.identity_dir, shared_config, args.certificate)
            print(f"Imported the certificate for peer node '{node_id}'. Restart this node to apply it.")
    except (ConfigurationError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
