import ssl
from pathlib import Path

from app.node.identity import NodeIdentity


def server_tls_options(identity: NodeIdentity, trust_bundle: Path) -> dict[str, object]:
    return {
        "ssl_certfile": str(identity.certificate_path),
        "ssl_keyfile": str(identity.key_path),
        "ssl_ca_certs": str(trust_bundle),
        "ssl_cert_reqs": ssl.CERT_REQUIRED,
    }


def client_ssl_context(identity: NodeIdentity, peer_certificate: Path) -> ssl.SSLContext:
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(peer_certificate))
    context.check_hostname = False
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_cert_chain(certfile=str(identity.certificate_path), keyfile=str(identity.key_path))
    return context
