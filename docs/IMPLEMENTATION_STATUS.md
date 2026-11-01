# Implementation Status

Last updated: 2026-11-01

## Overall status

- Documentation setup and architecture clarification: COMPLETED
- Stage 1 (project foundation): IN PROGRESS
- Stage 2 (cryptographic foundation): IN PROGRESS (interoperability foundation verified; wallet creation and encrypted local storage verified; wallet backup/export/import not started)
- Application implementation: Stage 3 (blockchain core) COMPLETED; Stage 4 (local persistence) COMPLETED; Stage 5A (node identity and secure peer connectivity) COMPLETED; Stage 5B (block exchange and chain synchronization) implementation COMPLETED, with automated verification recorded in the Stage 5 section; Stage 5C (pending transaction pool and transaction propagation) implementation COMPLETED, with automated verification recorded in the Stage 5 section; Stage 6 (registration and participants): backend COMPLETE IN DEVELOPMENT, not yet verified on Windows 11 or the three-laptop network; Stage 7 (e-waste workflows): backend COMPLETE IN DEVELOPMENT, not yet verified on Windows 11 or the three-laptop network; Stage 8 (processing and traceability): backend COMPLETE IN DEVELOPMENT, not yet verified on Windows 11 or the three-laptop network; Stage 9.1 (read-only application API) implemented; Stage 9.2 (write-transaction API) implemented; remaining Stage 9 phases, Stages 10 and 11: NOT STARTED
- Backend (Python): blockchain core, JSONL storage, startup integration, node identity, mutual TLS peer connectivity and status are implemented. In the Stage 5C session, the full backend suite passed 283 tests (Stages 3, 4, 5A, 5B, 5C, health and configuration). Windows verification has not been performed.
- Transaction propagation and the in-memory pending transaction pool are implemented (Stage 5C). Registration and the peer UI have not been implemented.
- Real node identities and certificates are created only by the provisioning command on each operator's laptop. No identity, certificate or genesis data has been generated for the three-node network.

## Status labels

- `NOT STARTED`: no work has begun on the stage.
- `IN PROGRESS`: work has begun but the stage is not verified.
- `COMPLETED`: the stage is implemented, reviewed and tested as required by the specification.

## Documentation and architecture clarifications completed; remaining decisions are tracked below.

The following are documented in `docs/PROJECT_SPECIFICATION.md` (Implementation Architecture Clarifications, C1 to C9) and reflected in the other project documents:

- Browser-side participant wallet generation, encryption, storage and signing; Python verifies signatures only.
- Credential separation between participant wallets, node identities, operator passwords and SMTP credentials.
- Mutual TLS with certificate fingerprint pinning, manual provisioning and renewal rules.
- Shared, versioned network configuration versus unique per-node private configuration.
- Browser origin limitation and encrypted wallet export and import.
- Frontend delivery trust limitation and the trusted-operator assumption for the demonstration.
- Windows 11 as the deployment target, separate from the Linux development environment.

## Stage summary

| Stage | Name | Status |
| --- | --- | --- |
| 1 | Project foundation | IN PROGRESS |
| 2 | Cryptographic foundation | IN PROGRESS |
| 3 | Blockchain core | COMPLETED |
| 4 | Local persistence | COMPLETED |
| 5 | Three-node network | IN PROGRESS (5A, 5B and 5C implementation completed; real three-laptop verification outstanding) |
| 6 | Registration and participants | BACKEND COMPLETE IN DEVELOPMENT |
| 7 | E-waste workflows | BACKEND COMPLETE IN DEVELOPMENT; NOT VERIFIED ON WINDOWS 11 OR ON THE THREE-LAPTOP NETWORK |
| 8 | Processing and traceability | BACKEND COMPLETE IN DEVELOPMENT; NOT VERIFIED ON WINDOWS 11 OR ON THE THREE-LAPTOP NETWORK |
| 9 | API and application | IN PROGRESS (Stage 9.1, 9.2, 9.3 and 9.4 implemented) |
| 10 | Node management | NOT STARTED |
| 11 | Integration and deployment | NOT STARTED |

## Stage details

### Stage 1 - Project foundation

Status: IN PROGRESS

Deliverables:
- Project structure.
- React setup.
- Python environment.
- FastAPI setup.
- Configuration management (shared and per-node separation, section C4).
- Code quality and test structure.

Completed work and verification (2026-10-31, Linux development environment):
- Frontend: React 19 with Vite and TypeScript. A Node connection panel calls `/api/health` and shows connected only when the response is OK and its body has `status: "ok"`; failures and malformed bodies show an unavailable state with retry. Typecheck passed, 5 Vitest tests passed, and the production build succeeded.
- Backend: FastAPI application factory `create_app`, health endpoint `GET /api/health`, generic 500 handler, and fail-fast loading of private node settings and the shared network configuration (unknown keys, including node-specific keys, are rejected). 29 pytest tests passed using temporary directories and environment variables only.
- Live check (2026-10-31): the backend was started with uvicorn on port 8000 using a temporary configuration; `/api/health` returned 200 with `{"status":"ok"}`. After stopping it, the same request failed to connect; after restarting it, the request returned 200 again. Pytest (29 tests) and frontend tests (5) and build passed again after the environment was rebuilt.
- Integration checks not performed: no Vite development server was started in this environment (dev servers cannot be run from the shell here), and no browser preview was available to inspect. The browser behavior for connected, unavailable, retry and recovery states is therefore NOT verified. The frontend unavailable and retry logic is covered only by unit tests on the health check function, not by the rendered panel.
- Repository: root `.gitignore` covers node_modules, dist, backend/.venv, __pycache__ and .pytest_cache.

Not yet verified or decided:
- Browser-level check that the React panel shows connected, unavailable, retry and recovery states through the Vite dev proxy. Not verified: no browser preview or dev server was available.
- The backend virtual environment was rebuilt on 2026-10-31 because the previous one was no longer present; requirements were reinstalled from the pinned files.
- Frontend delivery: the dev proxy (`/api` to the backend) is used for development. Serving the built frontend from FastAPI on the same origin, as required for deployment, is not implemented yet.
- Fresh-environment install of `backend/requirements.txt` has not been repeated; packages were installed and listed with pip freeze.
- Windows 11 start-up of the backend and frontend has not been tested.
- Python 3.11 is the interpreter used; the system Python lacked venv and pip, so pip was bootstrapped into the virtual environment manually.

Pending work: the items listed above, then a final review against the Stage 1 deliverables.

### Stage 2 - Cryptographic foundation

Status: IN PROGRESS

Deliverables:
- SHA-256 utilities.
- Canonical serialization.
- ECDSA secp256k1 signing and verification.
- Wallet creation in the browser.
- Encrypted wallet storage (AES-GCM with Argon2id or scrypt).
- Wallet backup, export and import, including restoration of the same identity (C5).
- Selection of cryptographic libraries checked for browser and Windows compatibility.

Completed work (2026-10-31, Linux development environment):
- Stage 2A design decisions were recorded; owner decisions D11 to D22 remain open (see blockers).
- Stage 2B interoperability foundation: browser and Python implementations of canonical serialization, strict JSON parsing from raw bytes, SHA-256, domain-separated hashing, wallet address derivation, compressed public-key validation, compact low-S signature validation and verification.
- Shared test vectors in `test-vectors/crypto-vectors.json`, consumed by both Vitest and pytest. The private keys in the file are fixed test values only.
- Browser signing (interoperability only) produces the exact 64-byte low-S signature in the vectors, and Python verifies it. Canonical bytes and digests match between the browser and Python implementations for every vector.
- Results: Vitest 77 tests passed, typecheck passed, production build passed, pytest 99 tests passed.
- Review corrections (2026-10-31): Python canonical serialization now sorts object keys by their raw UTF-8 bytes (previously by escaped form), with a new shared vector (`sorts escaped keys by raw UTF-8 bytes`) that failed before the fix. The Python strict JSON parser now requires a caller-supplied byte limit, checks it before decoding, and rejects nesting deeper than 32 before parsing, so deep input raises `ValueError`. Non-string object keys and non-string hex input raise `ValueError`.
- Results after corrections: Vitest 78 tests passed, typecheck passed, production build passed, pytest 112 tests passed.
- Browser strict JSON parser byte-limit correction (2026-10-31): `parseStrictJsonBytes` now requires an explicit `maxBytes` argument with no default, checks `bytes.byteLength` against it before UTF-8 decoding, and rejects oversized input using the existing parser error conventions. The depth limit of 32 and all existing strict JSON validation rules are unchanged. The two test call sites in `src/crypto/canonical.test.ts` now pass an explicit limit. New tests cover input exactly at the byte limit, input exceeding the byte limit, and empty input.
- Results after browser byte-limit correction: Vitest 81 tests passed, typecheck passed, production build passed.
- Stage 2C wallet creation and encrypted local storage (2026-10-31, Linux development environment): browser-only participant wallet creation using secp256k1 (Noble CSPRNG), scrypt KDF (N=16384, r=8, p=1, dkLen=32) with AES-256-GCM encryption, IndexedDB storage of the encrypted envelope, wallet session with unlock/lock and 15-minute inactivity timeout, and a minimal wallet UI in App.tsx (create, unlock, lock, address display).
- Stage 2C results: Vitest 129 tests passed (48 wallet + 81 existing), typecheck passed, production build passed. No regressions in existing Stage 2B tests.
- Measured scrypt KDF derivation time (development environment): 75-82 ms per derivation (three runs: 82 ms, 75 ms, 78 ms). This is the Linux development environment, not the 8 GB Windows laptop benchmark.
- Libraries: @noble/hashes, @noble/curves and @noble/ciphers 2.4.0 (browser); coincurve 21.0.0 (Python verification only). fake-indexeddb 6.0.0 added as a devDependency for IndexedDB test support.
- Remaining limitations: the transaction size limit to pass to the strict JSON parser is not yet wired to any production caller (none exist yet); Windows installation remains untested.

Not verified or not started:
- Scrypt cost parameter benchmark on the 8 GB laptop: NOT RUN (the 75-82 ms measurement above is on the Linux development environment, not the deployment target).
- Windows 11 installation of the browser and Python dependencies, including the coincurve wheel: NOT TESTED.
- Browser UI behavior (wallet create/unlock/lock/export/import/restore flows) was not verified through a browser preview or dev server; the UI is covered only by unit tests on the wallet session, backup format and storage modules, not by visual inspection of the rendered panel.

Pending work: the scrypt benchmark on the 8 GB laptop, Windows verification, and resolution of owner decisions D11 to D22.

Stage 2D wallet backup and restore (2026-11-01, Linux development environment):
- Encrypted wallet export and import implemented. The existing Stage 2C encrypted envelope is serialized to a versioned `.ewallet` JSON file with hex-encoded binary fields (salt, nonce, ciphertext). No re-encryption, no new KDF, no plaintext private key exposure.
- Files created: `src/wallet/backupFormat.ts` (backup file format: serialize/parse envelope, encode/decode backup). Files modified: `src/wallet/walletSession.ts` (added `exportWalletBackup` and `importWalletBackup` functions), `src/App.tsx` (added export, restore, and file-selection controls to the wallet panel).
- Backup format: JSON object with `format` ("ewaste-wallet-backup"), `backupVersion` (1), and `envelope` (serialized wallet envelope with hex-encoded salt/nonce/ciphertext). Maximum backup size 64 KB.
- Export flow: loads the encrypted envelope from IndexedDB, validates it, serializes to JSON, returns content and a filename (`wallet-<short-address>.ewallet`). The UI triggers a browser download via Blob URL.
- Import flow: parses and validates the backup file (format, version, required fields, envelope validation before KDF), checks for duplicate address in IndexedDB, verifies the password by running the existing `openEnvelope` decryption and key re-derivation, then stores the original encrypted envelope. Temporary private key buffer is zeroed. Failed imports leave existing storage unchanged.
- Security checks: no plaintext private key in backup, no password in backup, pre-KDF envelope validation, duplicate-address rejection, buffer zeroing on success and failure paths, 64 KB size limit.
- Tests added: 13 new tests covering export produces valid backup, export preserves envelope, export fails for non-existent wallet, export excludes plaintext, import reconstructs envelope, correct password restores identity, restored wallet unlocks and signs, incorrect password rejected, malformed backup rejected, unsupported version rejected, tampered ciphertext rejected, duplicate address rejected without overwrite, failed import does not modify existing storage.
- Stage 2D results: Vitest 62 wallet tests passed (13 backup + 49 existing wallet), typecheck passed, production build passed. No regressions.
- Not verified: browser UI behavior for export/download and restore/file-selection was not verified through a browser preview; the download and file-reading logic is covered only by unit tests on the backup format and session functions.

HTTP security limitation (Stage 2C): the application may be delivered over HTTP during development. An attacker able to modify the JavaScript delivered over HTTP could capture the wallet password or access decrypted key material. Peer-to-peer mutual TLS does not protect browser-to-node JavaScript delivery. HTTPS remains deferred to the planned deployment stage.

### Stage 3 - Blockchain core

Status: COMPLETED (verified in the Linux development environment through the backend test suite)

Deliverables:
- Block structure.
- Transaction structure.
- Genesis configuration generated deterministically from the shared configuration.
- Block hashing.
- Proof of Work.
- Block validation.
- Cumulative-work calculation.
- Chain selection.

Completed work: Block and transaction structures, block hashing, Proof of Work, block validation, cumulative-work calculation, deterministic chain selection (greatest cumulative work, then lexicographic tip-hash tie-break) and mining, all covered by backend tests.

Pending work: No real genesis configuration has been generated. It depends on the shared configuration agreed after node provisioning (blocker 6). Difficulty benchmarking on the 8 GB laptop is pending (blocker 7).

### Stage 4 - Local persistence

Status: COMPLETED (verified in the Linux development environment through the backend test suite)

Deliverables:
- JSONL block storage.
- File locking.
- Canonical-chain metadata.
- Startup validation.
- Crash recovery.
- Backup export and import.

Completed work: JSONL block storage with record files, an exclusive data lock, canonical-chain tip metadata, startup validation, crash recovery and backup, all covered by backend tests. Startup holds the lock and releases it on shutdown.

Pending work: Windows file-locking behaviour has not been verified.

### Stage 5 - Three-node network

Status: IN PROGRESS (5A and 5B implementation completed; real three-laptop verification outstanding)

Deliverables:
- Node identities and certificates, with manual provisioning (section 16 of the architecture overview, C3).
- Mutual TLS with certificate fingerprint pinning.
- Peer configuration.
- Transaction announcement.
- Block exchange.
- Chain synchronization.
- Fork handling.
- Reorganization.
- Network status.

Stage 5B completed work: read-only peer endpoints `/peer/tip`, `/peer/locate` and `/peer/blocks` (at most 8 blocks per request, bounded locator and response size); a streaming, size-capped peer client; and a chain synchronizer that runs after each successful peer check. Received blocks are linked, validated through the existing Stage 3 rules and stored through the existing Stage 4 storage, which keeps competing branches and selects the canonical chain by cumulative work. Storage work in the synchronizer runs on a single worker that is awaited at shutdown before storage closes. Automated verification: `tests/test_block_exchange.py` and the focused Stage 3, 4, 5A, health and configuration run passed 187 tests in the Linux development environment; the full suite was not rerun. Windows 11 and the three-laptop test on university Wi-Fi are not performed.

Pending work: Windows 11 verification; real three-laptop test on university Wi-Fi; later stages (Stage 6 onward).

Stage 5C completed work (Linux development environment, see `docs/STAGE_5C_COMPLETION_REPORT.md`): an in-memory pending transaction pool with bounded capacity (1000), deterministic ordering (timestamp, then transaction ID), admission states accepted, known, confirmed, rejected and unavailable, and reconciliation with the canonical chain after every synchronization batch and at startup; transaction announcement over the existing mutual TLS peers through `POST /peer/transactions` (strict JSON, bounded size); relay with origin exclusion on a bounded four-worker pool with two attempts; pending transactions re-sent to a peer when it reconnects; deterministic eligible-transaction selection for block construction (count and size limits). Automated verification: 13 pool tests and 8 propagation tests, and the full backend suite passed 283 tests. Block construction does not yet consume the selection, and the pool is memory-only by design. Windows 11 verification and the three-laptop test are not performed.

Stage 5A completed work (Linux development environment, see `docs/STAGE_5A_COMPLETION_REPORT.md`): unique node identity and self-signed certificate per laptop created by a provisioning command and never regenerated on restart; trusted node list in shared configuration; mutual TLS with certificate pinning; peer compatibility checks (node ID, network ID, protocol version, genesis hash); peer monitor with per-peer status and bounded retries. The backend suite passed 247 tests.

Pending work: network status. Windows 11 verification and the real three-laptop test on university Wi-Fi have not been performed. The `cryptography` dependency (pinned at 50.0.2 in requirements.txt) is used for X.509 certificate creation and is approved by the owner.

### Stage 6 - Registration and participants

Status: BACKEND COMPLETE IN DEVELOPMENT; NOT VERIFIED ON WINDOWS 11 OR ON THE THREE-LAPTOP NETWORK

Deliverables:
- Wallet registration.
- SMTP configuration (per-node private configuration).
- OTP verification.
- Role selection.
- On-chain registration.
- Email change.
- Wallet suspension.

Completed work (backend, Linux development environment; the backend suite passed 409 tests on the final run):
- Trust epochs and attestations: registration and email-change attestations are P-256 ECDSA signatures over a domain-tagged canonical body (`EWASTE-ATTESTATION-V1`) that binds purpose, wallet, role, issuer, epoch, request ID, nonce and issue time. Verification checks the signing node's status (active, retired or revoked) at the block height in force. Registration attestations must be included in a block within 24 hours of issuance.
- Participant rules (`participant.register`, `participant.email-change`, `participant.suspend`): single registration per wallet, immutable role, purpose and wallet matching, single-use attestations, role match on email change, and rejection of business transactions from suspended wallets. Rules run both at block validation and at pool admission.
- Participant state is recomputed from the canonical chain on every read, so reorganizations are handled without stored participant state.
- Certificate rotation and compromise: each node has a separate TLS certificate and attestation key, both listed in a trust epoch. Rotation lists the old certificate as retired alongside its active replacement in a new epoch, which takes effect at a block height. Attestations are checked against the epoch in force at the height where they are included, so a retired key is refused for attestations included at or after the rotation height and stays valid for earlier ones. Revocation takes effect at the revoking epoch's activation height, and a revoked node cannot return. Peers exchange a hash of their trust configuration when connecting and refuse the connection on mismatch. The configuration is read at startup, so a node must restart to apply a new one. Tests are in `tests/test_trust_rotation.py`. The mismatch refusal is tested at the compatibility-check level, not over a running network.
- SMTP delivery through any STARTTLS SMTP server configured by environment variables (`EWASTE_SMTP_HOST`, `EWASTE_SMTP_PORT`, `EWASTE_SMTP_USERNAME`, `EWASTE_SMTP_PASSWORD`, `EWASTE_SMTP_FROM`). Delivery failures are reported to the caller.
- OTP: 6 digits, 10-minute validity, 5 failed attempts, 60-second resend interval, 3 resends per hour, persisted per node in `otp-state.json`. Email addresses are keyed by an HMAC with a per-node salt, not stored in plain text.
- Contact storage: node-local, encrypted, append-only JSONL, AES-256-GCM with data keys wrapped by a master key. Lookup uses an HMAC of the normalized email.
- Email-change code requests and attestation requests must carry a wallet signature (secp256k1, compact form) over a domain-tagged body (`EWASTE-PARTICIPANT-REQUEST-V1`) that binds purpose, wallet, email address and issue time. Signed requests expire after 10 minutes.
- HTTP API under `/api/participants`: registration codes and attestations, email-change codes and attestations, transaction submission, and participant lookup. Status codes: 400 wrong or exhausted code, 401 missing or invalid wallet signature on email change, 403 suspended wallet, 404 unknown wallet, 409 duplicate registration, 422 invalid input, 429 rate limit, 502 delivery failure, 503 SMTP not configured or pool full.

Pending work:
- Backup and erasure: contact records are retained for 24 hours after a superseded key is replaced. Operator disk copies, backups or snapshots taken outside the application are outside the application's control and are not erased by it.
- Rate limits are local to each node. Each node keeps its own OTP state file, so a user can request codes from different nodes and receive more than the network-wide limit. This is a known limitation.
- The React participant interface for these flows has not been built.
- Windows 11 verification and the three-laptop test on university Wi-Fi have not been performed.

### Stage 7 - E-waste workflows

Status: BACKEND COMPLETE IN DEVELOPMENT; NOT VERIFIED ON WINDOWS 11 OR ON THE THREE-LAPTOP NETWORK

Deliverables:
- Batch creation.
- Inventory accounting.
- Transfer requests.
- Sender and receiver approvals.
- Rejection and cancellation.
- Expiry.
- Receipt discrepancy.

Completed work (backend, Linux development environment):
- Transaction types: `batch.create`, `transfer.request`, `transfer.accept`, `transfer.reject`, `transfer.cancel`. Each is a signed transaction with the same envelope and txid rules as earlier stages.
- Quantities are integer grams only. Floats are refused by the canonical encoder before a transaction can be signed, and the ledger additionally requires a positive whole number of grams. Kilogram text is converted to grams with at most three decimal places (`kilograms_to_grams`).
- Batch creation: only a registered, active Generator can create a batch. Description is 1 to 500 characters.
- Transfers follow Generator to Collector, Collector to Transporter and Transporter to Recycler. A Recycler cannot start a batch transfer; its only permitted transfer is recovered material to a Material Processor (Stage 8). Self-transfer, skipped roles, unregistered or suspended receivers and senders are refused.
- Available quantity is holding minus reservations by pending transfers. A transfer cannot request more than the available quantity, so pending transfers never over-reserve a batch.
- Acceptance: only the designated receiver can accept, and only before `expires_at`. The actual quantity must be a whole number from 0 to the declared quantity. A lower quantity requires a discrepancy reason. A zero-quantity receipt also requires a loss approval signed by the sender over a domain-tagged digest (`EWASTE-LOSS-APPROVAL-V1`) covering the transfer ID and reason. Reason and approval are refused for an exact receipt.
- Rejection: only the designated receiver, with a non-empty reason. Cancellation: only the original sender, and only while pending. Both release the reservation without changing ownership.
- Expiry: a pending transfer expires when a block's timestamp reaches `expires_at`, 48 hours after the request block's timestamp. Expiry uses block timestamps only, runs at the start of every block's state transition, and releases the reservation.
- Discrepancy accounting: each batch's quantity is held by its current holders, or recorded as discrepancy when a receipt is short. Holdings plus discrepancy always equal the declared batch quantity.
- Business state is derived from the canonical chain on every rebuild, so reorganizations need no stored state. The pending pool re-admits transactions removed by a reorganization in deterministic order (timestamp, then transaction ID), and rejects those that no longer apply.
- Block validation and pending pool admission use the same ledger, so their rules cannot diverge.
- Automated verification: `tests/test_business_rules.py` (ledger rules, 66 tests), `tests/test_business_chain.py` (pool, validation, expiry and reorganization, 7 tests). The full backend suite passed 482 tests (409 earlier tests plus 73 Stage 7 tests), with 0 failures and 1 warning (the existing Starlette `httpx` deprecation). The Stage 7 tests were run three times with identical results.

Known limitations:
- No HTTP endpoints, React screens or inventory views for these transactions yet (Stage 9). Transactions can only be submitted through the existing transaction path.
- Recovered-material transfers are added in Stage 8 (see that section).
- Expiry depends on block timestamps. A transfer whose time has passed is not expired until a block with a later timestamp is produced.
- The reorganization test runs on one node. Identical state across two running nodes after a live reorganization has not been tested over the network.
- Windows 11 verification and the three-laptop test on university Wi-Fi have not been performed.
### Stage 8 - Processing and traceability

Status: BACKEND COMPLETE IN DEVELOPMENT; NOT VERIFIED ON WINDOWS 11 OR ON THE THREE-LAPTOP NETWORK

Deliverables:
- Recycler processing.
- Recovered material creation.
- Material Processor processing.
- Residual accounting.
- Quantity conservation.
- Corrections.
- Traceability reconstruction.
- Completion calculations.

Completed work (backend, Linux development environment):
- Transaction types: `processing.record` and `record.correct`, with the same signed envelope and txid rules as earlier stages.
- Processing: a registered Recycler can process an e-waste batch it holds; a registered Material Processor can process recovered material it holds. Any other role, a missing input, or an input of the wrong kind (a Recycler on material, a Material Processor on a batch) is refused.
- Quantity conservation: input grams must equal the sum of recovered outputs plus residual exactly. Every quantity is a positive whole number of grams (residual may be zero). Outputs: 1 to 20 per operation, each with a description of 1 to 500 characters. The processing method is 0 to 500 characters.
- Available quantity is checked before processing, so partial processing leaves the remainder held. Duplicate operations are refused.
- Recovered-material transfer: only a Recycler can transfer recovered material, and only to a Material Processor, as set out in the permitted role transitions (sections 11.1 and 13.4). Acceptance, rejection, cancellation and expiry use the Stage 7 rules, pending transfers reserve material quantity, and a discrepancy on receipt is recorded. Material Processor outputs cannot be transferred onward. A Recycler cannot transfer batches to a Material Processor.
- Recovered material IDs are derived from the processing transaction ID and the output's position (`<txid>-<index>`). They are unique by construction, and each output records its source operation, parent item, creator, description and quantity.
- Residual is recorded on the processing operation and is not held by anyone after processing. Batch and material status report residual grams, derived from the operations that consumed each item. Residual is counted within processed grams, not remaining grams, so remaining, processed and discrepancy grams together equal the item's quantity. Each operation's residual is counted once, under its input item.
- Corrections: only the wallet that created the original batch or processing record can correct it. A correction references an existing batch or processing record and must have a non-empty explanation. Corrections are recorded as new signed transactions and never change the original record, any quantity, any balance or any lineage quantity. Corrections add an explanation only; compensating quantity adjustments are not supported (see Known limitations).
- Completion: a batch is completed when nothing is held by any participant and no transfer is pending. Recovered material outputs do not keep the batch active. A material is completed when nothing is held. Partial processing is never completion.
- Traceability: lineage runs from the original batch, through accepted custody transfers and processing operations, to the item, and includes corrections attached to each record.
- Historical access: `can_view_history` allows a wallet that appears in the item's lineage or in any transfer for its root batch, including pending, rejected, cancelled and expired transfers. Access is kept after custody ends. Uninvolved wallets are refused. Section 14.2 requires read-only access for participants "involved in a batch or material" but does not say whether a named party to an unaccepted transfer is involved; this implementation counts them (see Decisions).
- Block validation, pool admission and reorganization use the same chain ledger as Stage 7. Processing state is rebuilt from the canonical chain, so a reorganization removes processing and restores inventory without special handling.
- Automated verification: `tests/test_processing_rules.py` (27 tests), `tests/test_traceability.py` (26 tests), `tests/test_processing_chain.py` (11 tests), `tests/test_material_transfer.py` (17 tests). The full backend suite passed 563 tests (482 Stage 7 and earlier tests plus 81 Stage 8 tests), with 0 failures, 0 skipped and 1 warning (the existing Starlette `httpx` deprecation). The residual tests cover per-item residual accounting, including a material with a receipt discrepancy. The reorganization tests cover material transfers, material completion, batch completion with residual, and corrections, with removal and restoration checked where relevant.

Decisions taken within the specification:
- A Recycler processes e-waste batches only. Recovered material cannot be processed by a Recycler.
- Correction scope is an explanation only (see Known limitations).
- Historical involvement counts parties to pending, rejected, cancelled and expired transfers as involved. This is an interpretation of section 14.2 that needs approval.
- Corrections can target batches and processing records only, not recovered material.

Known limitations:
- Recovered material held by a Recycler stays open, with its quantity still held, until the Recycler transfers it to a Material Processor and that processor fully processes it. A Recycler cannot process recovered material itself under this implementation, which follows the role split in section 12 (Recyclers process e-waste batches; Material Processors process recovered material).
- Corrections do not support compensating quantity adjustments. Section 12.5 requires "corrected or compensating information"; the current implementation provides the explanation and the reference to the original record only. This is a known gap against that requirement.
- Transfer reservations cannot block processing under the current rules, because a reservation is always held by the sender of a pending transfer, and no processor sends transfers. The available-quantity check is implemented and applies to any holder.
- No HTTP endpoints, React screens or traceability views for these transactions yet (Stage 9).
- Windows 11 verification and the three-laptop test on university Wi-Fi have not been performed.

### Stage 9 - API and application

Status: COMPLETED (Stage 9.1 to 9.4 implemented; the operator REST APIs were completed in Stage 10)

Deliverables:
- Participant REST APIs.
- Operator REST APIs.
- Peer REST APIs.
- React participant interface.
- Wallet interaction, including export and import and browser-origin explanations.
- Role-based navigation.
- Dashboards.
- Notifications.
- Traceability views.
- Network status.

Stage 9.1 completed work (Linux development environment, 2026-11-01):
- Read-only application API module `backend/app/api/application.py` exposing existing blockchain-derived state through 12 endpoints under `/api/app`, registered in `main.py` alongside the existing health and participant routers.
- All endpoints read canonical-chain state by rebuilding a `ChainLedger` from `storage.store.canonical_chain` under the storage lock. No new source of truth, no duplicated business logic, no new pending pool.
- Endpoints: `GET /api/app/batches` (list), `GET /api/app/batches/{batch_id}` (detail with completion and discrepancy), `GET /api/app/batches/{batch_id}/transfers` (transfer history), `GET /api/app/batches/{batch_id}/traceability` (lineage), `GET /api/app/materials` (list), `GET /api/app/materials/{material_id}` (detail with completion), `GET /api/app/materials/{material_id}/traceability` (lineage), `GET /api/app/processing` (list operations), `GET /api/app/processing/{operation_id}` (detail), `GET /api/app/transactions/{txid}` (status: confirmed, pending or unknown), `GET /api/app/chain` (network ID, protocol version, tip hash, tip height, difficulty).
- Response structures include both integer grams and kilograms (3 decimal places) for frontend convenience. Completion status reports remaining, processed, residual, discrepancy and pending grams. Transfer responses show status, actual grams, reason, expiry and timestamps.
- Unknown batch, material or operation IDs return 404. Transaction status for unknown IDs returns `{"status": "unknown"}` with 200.
- Empty chain returns genuine empty lists, not sample content.
- Reorganization is handled automatically: state is rebuilt from the canonical chain on every request, so batches and materials disappear after a fork replaces them.
- Automated verification: 28 tests in `tests/test_application_api.py` covering empty-chain responses, batch listing and detail, transfer history with pending and accepted states, material listing and detail, processing operations, traceability with corrections, transaction status (confirmed, pending, unknown), chain status, reorganization behavior and pending-vs-confirmed completion. Full backend suite passed 591 tests (563 existing + 28 new), 0 failures, 1 warning (the existing Starlette deprecation).

Stage 9.1 files:
- Created: `backend/app/api/application.py`, `backend/tests/test_application_api.py`.
- Modified: `backend/app/main.py` (added `application_router` import and `include_router`).

Stage 9.2 completed work (Linux development environment, 2026-11-01):
- Write-transaction API added to `backend/app/api/application.py` as 8 POST endpoints under `/api/app`, reusing the existing transaction submission pipeline entirely. No new pool, relay, validation system, or business logic was created.
- Generic endpoint: `POST /api/app/transactions` accepts any signed business transaction, decodes it via the existing `decode_transaction_object()`, and submits through the existing `relay.submit_local()` (which calls `pool.admit()` then announces to peers). Response: `{"state": "accepted|known|confirmed|rejected|unavailable", "detail": "...", "txid": "..."}`.
- Typed endpoints: `POST /api/app/transactions/batch.create`, `/transfer.request`, `/transfer.accept`, `/transfer.reject`, `/transfer.cancel`, `/processing.record`, `/record.correct` — each validates that the transaction type matches the endpoint before submitting through the same path. Unknown typed endpoints return 405.
- Rejected transactions return 422 with the rejection detail. Pool-full returns 503. Already-pending returns 200 with state "known". Already-confirmed returns 200 with state "confirmed". Accepted-but-not-confirmed returns 200 with state "accepted".
- Transaction types supported: `batch.create`, `transfer.request`, `transfer.accept`, `transfer.reject`, `transfer.cancel`, `processing.record`, `record.correct`.
- Existing components reused: `decode_transaction_object` (block_records.py), `TransactionRelay.submit_local` (transaction_relay.py), `PendingTransactionPool.admit` (pending_pool.py), `validate_transaction` (validation.py), `ChainLedger.check` (ledger.py), all business and processing ledger rules. No duplication.
- Wallet signing flow: the browser wallet signs the transaction locally (secp256k1, compact form). The node receives only the signed transaction dict, decodes and validates its structure, verifies the signature through the existing `validate_transaction()`, checks business rules via `ChainLedger.check()`, and admits to the existing pending pool. The node never receives a private key or password.
- Pending-vs-confirmed distinction: the response state field accurately distinguishes accepted (pending), known (already pending), confirmed (on canonical chain), rejected (not admitted), and unavailable (pool full). The existing `GET /api/app/transactions/{txid}` endpoint distinguishes confirmed (with block height and hash) from pending (in pool) from unknown.
- Automated verification: 35 tests added to `tests/test_application_api.py` covering batch creation (valid, wrong type, invalid structure, missing field, rejected, duplicate/known, confirmed), custody transfers (valid request/accept/reject/cancel, wrong role, self-transfer, insufficient quantity, wrong receiver accept, duplicate), recovered material transfers (valid, unauthorized sender), processing (valid, conservation violation, unauthorized processor, multiple outputs), corrections (valid, unauthorized), signature tampering (corrupted signature, tampered payload), blockchain integration (pending status, confirmed status, pool membership for accepted and rejected, suspended generator, full lifecycle). Full backend suite passed 626 tests (591 Stage 9.1 and earlier + 35 new), 0 failures, 1 warning (the existing Starlette deprecation).

Stage 9.2 files:
- Modified: `backend/app/api/application.py` (added 8 POST endpoints, `TransactionSubmission` model, `_relay` and `_submit` helpers), `backend/tests/test_application_api.py` (added 35 write-transaction tests, `network_now` and `app_client_now` fixtures with current-time genesis for transfer expiry tests), `docs/IMPLEMENTATION_STATUS.md`.

Stage 9.3 completed work (Linux development environment, 2026-11-01):
- React participant interface built on the existing backend APIs and browser wallet. No backend business logic duplicated in React. All transaction signing occurs in the browser; the node receives only signed transactions.
- Wallet panel: create, unlock, lock, export backup, and restore from backup file. Wallet inactivity lock (15 minutes). Browser-origin limitation text shown to participants.
- Registration panel: email entry, role selection, OTP verification code entry, and attestation submission. Uses the existing `/api/participants` registration endpoints.
- Role-based navigation: seven navigation items (Dashboard, Batches, Transfers, Processing, Materials, Traceability, Transactions, Node status) shown only after wallet unlock and registration.
- Dashboard: chain status, pending incoming transfer requests, batches created (Generator) or all batches (other roles), processing operations and recovered materials (Recycler and Material Processor), and peer status. All data comes from the existing backend list endpoints. No client-side custody-balance reconstruction.
- Batches screen: list all batches with completion status; create form for Generators with description and quantity in kilograms.
- Transfers screen: outgoing transfer requests with item selection, receiver public key, and quantity; incoming pending transfers with accept (including actual-quantity and discrepancy reason) and reject (with reason); cancel own pending outgoing transfers; transfer history table. Transfers are fetched per batch through the view-proof-protected endpoint.
- Processing screen: recording processing operations for Recycler and Material Processor with input item, input quantity, multiple outputs, residual, and method. Quantity conservation is validated client-side as a form check only; the backend remains authoritative.
- Materials screen: list recovered materials with detail view and traceability lineage, using the view-proof-protected endpoints.
- Traceability screen: select a batch or material and view its lineage through the view-proof-protected endpoints.
- Transaction Status screen: look up a transaction by ID and see pending, confirmed (with block height and hash), or unknown status.
- Node Status screen: connection state, chain info, and peer status.
- View-proof mechanism: a wallet-signed proof (public key, item ID, issued timestamp, signature over a domain-tagged canonical body) is verified on the node for all protected detail and traceability endpoints. The node enforces the existing `can_view_history()` policy. Proof expiry is 10 minutes. The proof is bound to the specific item ID and wallet.
- Backend view-proof endpoints added to `application.py`: `POST /api/app/batches/{id}/view`, `/batches/{id}/transfers/view`, `/batches/{id}/traceability/view`, `/materials/{id}/view`, `/materials/{id}/traceability/view`. The original GET endpoints remain for backward compatibility.
- Backend peer-status endpoint: `GET /api/app/peers` using the existing `PeerMonitor.snapshot()`.
- Styling: `src/index.css` with restrained blue/grey palette, 8px spacing system, responsive breakpoints, and natural application wording. No gradients, animations, or decorative elements.
- UI text reviewed for natural language. No developer instructions, prompt fragments, stage descriptions, or placeholder text in the interface. Success messages distinguish pending pool admission from chain confirmation.
- No seed, demo, dummy, or fabricated runtime data introduced. All screens show genuine empty states when the chain has no relevant records.

Stage 9.3 files:
- Created: `src/screens/TransactionStatus.tsx`, `src/blockchain/viewProof.ts`, `src/blockchain/transaction.ts`, `src/api/client.ts`, `src/index.css`, `src/screens/Dashboard.tsx`, `src/screens/Batches.tsx`, `src/screens/Transfers.tsx`, `src/screens/Processing.tsx`, `src/screens/Materials.tsx`, `src/screens/Traceability.tsx`, `src/screens/NodeStatus.tsx`.
- Modified: `src/App.tsx` (wallet panel, registration panel, navigation, screen routing), `src/wallet/walletSession.ts` (exposes public key and sign function), `backend/app/api/application.py` (view-proof endpoints, peer-status endpoint), `docs/IMPLEMENTATION_STATUS.md`.

Automated verification (Linux development environment, 2026-11-01):
- TypeScript typecheck: clean, no errors.
- Production build: succeeds with no warnings.
- Frontend tests: 143 passed (5 test files: wallet 62, canonical 44, secp256k1 23, nodeHealth 5, hashing 9).
- Backend tests: 626 passed, 1 warning (existing Starlette httpx deprecation).
- Browser UI behavior was not verified through a browser preview or dev server; UI correctness is covered by code review and type/build checks only.

Known limitations:
- The Dashboard does not show per-holder custody balances or available/reserved/received/transferred quantity summaries because the backend API does not expose per-holder holdings. The backend `batch_status` and `material_status` report aggregate remaining/processed/residual/discrepancy/pending grams, not per-participant holdings. Adding per-holder holdings is a backend change outside Stage 9.3 scope.
- The Transfers screen fetches transfers per batch using view-proof-protected endpoints. For a large number of batches this results in many API calls. A combined transfers-listing endpoint does not exist in the current API.
- Registration requires a configured SMTP server. Without SMTP, OTP delivery fails and registration cannot complete.
- No browser preview or dev-server visual verification was performed in this environment.
- Windows 11 verification and the three-laptop test have not been performed.

Stage 9.4 completed work (Linux development environment, 2026-11-01):
- Notifications and transaction updates implemented as a polling-based notification area within the existing React application. No WebSockets, push services, external notification services, or new database introduced.
- Notification events detected from actual backend API data:
  - Incoming transfer request (receiver sees a new pending transfer).
  - Transfer accepted (sender sees their transfer was accepted, with received quantity).
  - Transfer rejected (sender sees their transfer was rejected).
  - Transfer cancelled (receiver sees an incoming transfer was cancelled).
  - Transfer expired (sender or receiver sees a transfer expired).
  - Processing operation confirmed (processor sees their operation is confirmed on the chain).
  - Batch completed (batch transitions to fully processed).
  - Recovered material fully processed (material transitions to completed).
- All events are derived from confirmed chain state only. Transfers and processing operations exist in the API only after block inclusion. The notification system never reports a locally-submitted transaction as confirmed.
- Duplicate prevention: each notification has a deterministic key (category + item IDs). A seen-IDs set persisted in sessionStorage suppresses duplicates across polling cycles and page refreshes within the same browser session. New notifications that have never been seen before appear as unread; previously-seen notifications are treated as read on restore.
- Read/unread state: notifications start as unread when first detected. Clicking a notification marks it read and navigates to the relevant screen. "Mark all as read" and "Clear all" controls are provided. Read state is persisted in sessionStorage.
- Polling: the `useNotifications` hook polls every 20 seconds using the existing backend list endpoints (`listBatches`, `listMaterials`, `listOperations`) and view-proof-protected transfer endpoints (`viewBatchTransfers`). Transfers are fetched per batch and per material with wallet-signed view proofs, respecting the existing `can_view_history()` authorization.
- Authorization: only transfers involving the participant's public key (as sender or receiver) generate notifications. Only processing operations by the participant generate notifications. Batch and material completion notifications are derived from public list endpoints. No private or restricted information is exposed through notifications beyond what the participant is already authorized to view.
- Reorganization handling: backend state is rebuilt from the canonical chain on every poll. If a reorganization removes a transfer or operation, the prior-state snapshot retains it, preventing re-notification if it reappears. A notification generated from a record that a reorganization later removes remains in the notification list as a historical event (it was confirmed at the time of detection); the participant can navigate to the relevant screen to see the current authoritative state, which may show the item as absent.
- Offline events: events that occurred while the participant was offline are detected on the next poll. On a fresh session (no prior state), all current transfers and operations appear as new, so the participant sees notifications for all relevant current events. The system cannot recover events that the backend no longer exposes (for example, a transfer removed by a reorganization that did not reappear).
- Notification navigation: clicking a notification navigates to the relevant screen (Transfers, Processing, Traceability, or Transaction Status). The Transaction Status screen accepts a `focusTxid` prop so a notification linked to a transaction ID can pre-fill and auto-look-up that transaction.
- Nav badge: the Notifications nav button shows an unread count badge when there are unread notifications. The badge reflects the actual unread count, not a decorative number.
- Empty state: when no notifications exist, the screen shows a genuine empty-state message. No fabricated or seed notifications.
- No backend changes: Stage 9.4 uses only existing backend API endpoints and the existing view-proof mechanism. No new backend endpoints, no new database, no new infrastructure.

Stage 9.4 files:
- Created: `src/notifications/types.ts` (notification and snapshot type definitions), `src/notifications/store.ts` (sessionStorage-backed deduplication, seen/read state, persistence helpers), `src/notifications/collector.ts` (pure functions that diff backend state against a prior snapshot to detect events), `src/notifications/useNotifications.ts` (React hook with polling, state management, dedup merge), `src/screens/Notifications.tsx` (notification list UI with read/unread, mark-all-read, clear, navigation links), `src/notifications/collector.test.ts` (23 tests), `src/notifications/store.test.ts` (18 tests).
- Modified: `src/App.tsx` (added Notifications screen, nav item with unread badge, `useNotifications` hook, `focusTxid` state, navigation callback), `src/screens/TransactionStatus.tsx` (added `focusTxid` prop for pre-fill and auto-lookup), `src/index.css` (notification list, item, unread, badge, and related styles), `docs/IMPLEMENTATION_STATUS.md`.

Automated verification (Linux development environment, 2026-11-01):
- TypeScript typecheck: clean, no errors.
- Production build: succeeds with no warnings.
- Frontend tests: 184 passed (7 test files: wallet 62, canonical 44, secp256k1 23, nodeHealth 5, hashing 9, notifications collector 23, notifications store 18).
- Backend tests: not run (no backend changes in Stage 9.4).
- Browser UI behavior was not verified through a browser preview or dev server; UI correctness is covered by code review and type/build checks only.

Known limitations:
- Notifications are session-scoped: the notification list and seen/read state are stored in sessionStorage and are lost when the browser tab is closed. This is acceptable for a polling-based notification area and avoids introducing unnecessary persistence infrastructure.
- The system cannot recover events that the backend no longer exposes after a reorganization removes them from the canonical chain.
- Polling interval is 20 seconds; events may take up to 20 seconds to appear after confirmation.
- The Transfers notification data is fetched per batch and per material using view-proof-protected endpoints, resulting in many API calls for a large number of items. This is the same pattern used by the Transfers screen and is a known limitation of the current API.
- No browser preview or dev-server visual verification was performed in this environment.
- Windows 11 verification and the three-laptop test have not been performed.

Pending work:
- Windows 11 verification and the three-laptop test are not performed.

### Stage 10 - Node operations and management

Status: COMPLETED

Deliverables:
- Node operational visibility (identity, chain height, pending count, storage health, sync status).
- Peer operations visibility (configured peers, connectivity state, last sync outcomes).
- Mining controls (start, stop, live status).
- Backup management (chain export and import).
- Operational reliability (graceful shutdown of background mining on app stop).
- Operator authentication and localhost enforcement for every node-management endpoint.

Completed work:
- Backend: added `backend/app/api/node_management.py` with a FastAPI router (`/api/node`) exposing node identity (`GET /info`), storage health (`GET /storage`), pending transaction count (`GET /pending`), last sync outcomes per peer (`GET /sync`), mining status and controls (`GET /mining`, `POST /mining/start`, `POST /mining/stop`), and backup export/import (`POST /backup/export`, `POST /backup/import`).
- Backend: added `backend/app/node/mining_controller.py` — a `MiningController` that runs mining on a daemon thread with a cancel event. Exposes `start()`, `stop()`, and `status()`. Selects eligible pending transactions, mines a block, adds it to storage, and reconciles the pool. State transitions (stopped/running/error), blocks mined, and last block hash/height are tracked.
- Backend: extended `backend/app/node/pending_pool.py` with a `count()` method.
- Backend: extended `backend/app/node/chain_sync.py` with `last_outcomes()` and per-peer `SyncOutcome` recording in `sync_peer()`.
- Backend: added `export_backup_from_store()` and `import_backup_to_store()` to `backend/app/storage/backup.py` so the node management router reuses the already-opened `ChainStorage` lock instead of re-opening the data directory (which would conflict with the live process). The original `export_backup()` / `import_backup()` functions remain for standalone use.
- Backend: updated `backend/app/main.py` to register the node management router, store `node_identity`, `MiningController`, and `chain_synchronizer` on app state, and stop mining in the shutdown handler.
- Backend: added 12 tests in `backend/tests/test_node_management.py` covering node info, storage health, pending count, sync status with no synchronizer, mining start/stop/status, backup export (success, refuse overwrite), backup import (from exported file, nonexistent file).
- Frontend: added node management types and API functions to `src/api/client.ts` (`getNodeInfo`, `getStorageHealth`, `getPendingCount`, `getSyncStatus`, `getMiningStatus`, `startMining`, `stopMining`, `exportBackup`, `importBackup` and their response interfaces).
- Operator authentication: `backend/app/crypto/password_verifier.py` stores the operator password only as a salted scrypt verifier (standard library, no new dependency). `backend/app/node/operator_sessions.py` issues random in-memory session tokens that expire after 15 minutes of inactivity, are cleared on node restart, and lock sign-in for 15 minutes after five consecutive wrong passwords.
- Operator authentication: all nine `/api/node/*` management endpoints require a valid session token and a loopback client address (127.0.0.1, ::1 or the IPv4-mapped form). Sign-in and sign-out (`POST` and `DELETE /api/node/session`) are also loopback-only. Forwarded address headers are never trusted. The public health endpoint, participant APIs and peer mutual TLS are unchanged.
- Operator authentication: the operator password is provisioned per node with `python -m app.node.provision set-operator-password`, which prints the `EWASTE_OPERATOR_PASSWORD_VERIFIER` line for the node's private configuration. The node refuses to start the management API with a malformed verifier; without a verifier, sign-in is unavailable.
- Frontend: `src/screens/NodeStatus.tsx` shows an operator sign-in form before any management data. The session token is kept in the browser tab's session storage only, sent as a bearer header, and cleared on sign-out or when the node reports the session has ended. The password is never stored, placed in a URL, or shown in the interface. Sign-in logic lives in `src/screens/OperatorSignIn.tsx`.
- Frontend: `src/api/client.ts` routes management calls through one authenticated helper and treats an unauthorized response as an ended session.
- Frontend: rewrote `src/screens/NodeStatus.tsx` to show node identity (node ID, listen/peer ports, certificate fingerprint, network ID, protocol version, configured peer count), chain info, storage health (block count, canonical height, tip hash, data directory, lock state), pending transaction count, mining status with start/stop controls, synchronization outcomes per peer, peer connectivity table, and a backup export/import panel with a file path input.

Files created:
- `backend/app/node/mining_controller.py`
- `backend/app/api/node_management.py`
- `backend/tests/test_node_management.py`
- `backend/app/crypto/password_verifier.py`
- `backend/app/node/operator_sessions.py`
- `backend/tests/test_operator_security.py`
- `backend/tests/test_password_verifier.py`
- `src/api/operatorSession.ts`
- `src/api/client.operator.test.ts`
- `src/screens/OperatorSignIn.tsx`

Files modified:
- `backend/app/config/node_settings.py` (optional operator verifier setting)
- `backend/app/node/provision.py` (`set-operator-password` command)
- `backend/app/storage/backup.py` (added store-based backup functions and `ChainStorage` import)
- `backend/app/node/pending_pool.py` (added `count()`)
- `backend/app/node/chain_sync.py` (added `last_outcomes()` and outcome recording)
- `backend/app/main.py` (router registration, app state wiring, mining shutdown)
- `src/api/client.ts` (node management types and API functions)
- `src/screens/NodeStatus.tsx` (full node operations screen)
- `docs/IMPLEMENTATION_STATUS.md`

Automated verification (Linux development environment, 2026-11-01):
- Backend tests: 638 passed (full suite), including 12 new node management tests and 35 storage/startup regression tests.
- TypeScript typecheck: clean, no errors.
- Production build: succeeds with no warnings.
- Frontend tests: 184 passed (7 test files, unchanged from Stage 9.4).
- Browser UI behavior was not verified through a browser preview or dev server; UI correctness is covered by code review and type/build checks only.

Security and architecture:
- No central server, master node, administrator role, or central database was introduced.
- Mutual TLS, certificate fingerprint pinning, and browser-side wallet signing are preserved.
- The node management router exposes operational data only; it does not expose private keys, wallet passwords, or another participant's records.
- Mining controls operate on the local node only and do not affect consensus rules.
- Backup export refuses to write inside the active storage directory or overwrite an existing file. Backup import validates every block against the network configuration before applying it and never replaces a longer active chain with a shorter one.

Operator authentication verification (Linux development environment, Python 3.11, pinned dev requirements):
- Backend: full suite 716 passed, including 90 focused tests for the password verifier, configuration and provisioning, sessions, sign-in limits, loopback enforcement, forged forwarding headers, and protection of all nine management endpoints.
- Frontend: typecheck clean, 193 tests passed (including 9 new tests for token handling, expiry and sign-out), production build succeeds.
- Browser UI behavior was not verified in a browser; the sign-in gate is covered by unit tests and build checks only.

Known limitations:
- Each node has its own operator password and its own in-memory sessions. Restarting a node signs out all operators on that node.
- Management is possible only from the node's own computer. An operator cannot manage a node remotely; remote management is not supported.
- The node serves the browser over plain HTTP on the local computer, so the password travels over the loopback interface unencrypted. Software already running on that computer could read it.
- Sign-in lockout (five wrong passwords, then 15 minutes) is shared by everyone who can reach the node from its own computer, so a local user can temporarily block the operator from signing in.
- The operator token is kept in the browser tab's session storage. Anyone using the unlocked computer while the session is open can use the management screen.
- There is no password recovery. A forgotten password is replaced by running the provisioning command again and restarting the node.
- The trusted-operator assumption for the frontend build still applies.
- Peer connectivity state and last sync outcomes depend on the existing peer monitor and chain synchronizer; the endpoints surface only data those services actually produce.
- No browser preview or dev-server visual verification was performed in this environment.
- Windows 11 verification and the three-laptop test have not been performed.

Pending work:
- Windows 11 verification and the three-laptop test are not performed.

### Stage 11 - Integration and deployment

Status: NOT STARTED

Deliverables:
- Unit tests.
- Integration tests.
- Security tests.
- Three-laptop network tests.
- Windows deployment procedure.
- Browser access tests.
- Restart and recovery tests.
- Performance tuning.

Completed work: None.

Pending work: All deliverables above. Deployment validation must be performed on all three Windows 11 laptops.

## Known blockers and open decisions

1. Network connectivity: university Wi-Fi may enable client isolation or firewall restrictions. Direct laptop-to-laptop reachability has not been verified.
2. Node certificate exchange: the secure channel for exchanging public certificates among the three operators has not been agreed (C3, step 3).
3. Certificate renewal activation: the procedure, timing and any transition period for a trusted-configuration update have not been agreed (C3, C9).
4. Trusted-node changes and historical attestations: it is not yet decided whether changes to trusted nodes affect previously issued email-verification attestations (sections 9.5 and C9).
5. Cryptographic libraries: exact libraries and versions are selected and pinned (Stage 2B). Windows installation has not been verified, and owner decisions D11 to D22 remain open.
6. Shared configuration and genesis: the shared configuration values must be agreed after node provisioning. The genesis configuration is generated only after that agreement.
7. Difficulty tuning: the Proof of Work difficulty must be benchmarked on the slowest (8 GB Intel) laptop (section 5.3).
8. SMTP provider: no email service has been selected or configured (section 9.4).
9. Deployment validation: the Windows 11 deployment procedure has not been written or tested on any laptop.


## Accepted academic limitations (not blockers)

- Participant wallets are tied to the browser origin and move between node addresses only by encrypted export and import (C5).
- A malicious or compromised node operator could serve modified application code (C6).
- Certificate fingerprint pinning depends on operators verifying fingerprints correctly (C8).
