# Stage 5A completion report: node identity and secure peer connectivity

Status: COMPLETED for the Linux development environment. Windows verification has not been performed.

## Scope delivered

- Unique node identity per laptop: node ID, private key, self-signed certificate and SHA-256 fingerprint, created once by the provisioning command.
- Identity is never regenerated on restart. Startup fails with a clear message if the identity is missing, incomplete, or does not match its certificate or the shared configuration.
- Shared network configuration now lists trusted node IDs and certificate fingerprints. Each entry is validated (lowercase hexadecimal fingerprint, unique IDs, unique fingerprints).
- Per-node settings add the peer service port, identity folder, and a comma-separated peer list (`node-id@host:port`).
- Peer service: a separate HTTPS listener on the peer port, requiring client certificates. It exposes one read-only hello endpoint returning node ID, network ID, protocol version and genesis hash.
- Mutual TLS with pinning: each node trusts only the certificates of peers that were imported after their fingerprint matched the shared configuration. A client connects only to the exact certificate pinned for that peer.
- Peer monitor: one task per configured peer. States are not checked, connected, unreachable, rejected (incompatible or TLS-refused) and certificate missing. Failed checks retry with doubling delay up to 60 seconds; connected peers are rechecked every 15 seconds. A failing peer never stops the node or other peers.
- Startup integration: the node holds its storage lock, starts the peer service only when at least one peer certificate is present, starts the monitor, and stops both on shutdown.

## Provisioning (per operator, on their own laptop)

1. Create the identity: `python -m app.node.provision create-identity --identity-dir <folder> --node-id <id>`. The private key stays in that folder.
2. Send only the public certificate file to the other operators through an agreed channel. Each operator checks the printed SHA-256 fingerprint with the sender.
3. Add all three node IDs and fingerprints to the shared network configuration, identical on all laptops.
4. Import each peer's certificate: `python -m app.node.provision import-peer --identity-dir <folder> --shared-config <file> --certificate <file>`. The import is refused if the fingerprint is not in the shared configuration, if it is the node's own certificate, or if it would replace a different certificate for the same node ID.
5. Restart the node. The peer service starts only after peer certificates exist, so a restart is required after importing.

## Dependencies

- `cryptography` 50.0.2 was added for X.509 certificate creation. Standard Python has no certificate builder, and coincurve cannot create certificates.
- `httpx` moved from development to runtime requirements because the peer client uses it.
- `cryptography` was installed into the system Python with `--break-system-packages`. Owner approval is still needed for this dependency.

## Design simplifications to review

- The node's TLS key pair is also its identity key. The architecture describes a separate identity key; a separate signing key is needed later for attestations and is not part of 5A.
- Certificates are self-signed and valid for 10 years. Renewal rules are still open (specification C9).
- Peer status is held in memory only and is not persisted or exposed through an API or UI yet.
- Peer certificate files and the generated trust bundle live in the identity folder. Both are excluded by the repository ignore rules.

## Tests

- Full backend suite (Stage 1 to 5A): 247 passed, 0 failed, in the Linux development environment.
- Stage 5A coverage: unique identities; restart without regeneration; refusal to create a second identity; missing, tampered or mismatched credentials; owner-only key permissions (POSIX only); unlisted identity refused at startup; peer import rules; peer settings and trusted-node validation; two nodes connecting with mutual authentication; unknown certificate rejected; network ID, protocol version and genesis mismatches rejected; unavailable peer reported without stopping the monitor; missing peer certificate reported; status changing to unreachable when a peer goes offline; startup connecting to a configured peer; startup refusing an unlisted identity.

## Not verified

- Windows 11: the identity folder permission behavior and the peer service have not been run on Windows.
- Real network across the three laptops on university Wi-Fi has not been tested.
- Browser UI for peer status has not been built or checked.

## Documentation still to update

- `docs/IMPLEMENTATION_STATUS.md`: resolved in the Stage 5B session. The stage table and the Stage 3, 4 and 5 sections now reflect the current status.
