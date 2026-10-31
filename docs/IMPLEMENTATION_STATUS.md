# Implementation Status

Last updated: 2026-10-31

## Overall status

- Documentation setup and architecture clarification: COMPLETED
- Stage 1 (project foundation): IN PROGRESS
- Stage 2 (cryptographic foundation): IN PROGRESS (interoperability foundation verified; wallet and encryption work not started)
- Application implementation (Stages 3 to 11): NOT STARTED
- No blockchain, backend, frontend, wallet, networking, certificate or deployment functionality has been implemented or verified.
- No keys, certificates, genesis data or runtime records have been generated.

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
| 3 | Blockchain core | NOT STARTED |
| 4 | Local persistence | NOT STARTED |
| 5 | Three-node network | NOT STARTED |
| 6 | Registration and participants | NOT STARTED |
| 7 | E-waste workflows | NOT STARTED |
| 8 | Processing and traceability | NOT STARTED |
| 9 | API and application | NOT STARTED |
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
- Remaining limitations: the browser strict JSON parser has no byte limit (the Python parser now does); the transaction size limit to pass to the parser is not yet wired to any caller; Windows installation remains untested.
- Libraries: @noble/hashes, @noble/curves and @noble/ciphers 2.4.0 (browser); coincurve 21.0.0 (Python verification only).

Not verified or not started:
- Wallet creation, encrypted wallet storage (scrypt with AES-256-GCM), wallet backup, export and import, and the wallet interface: NOT STARTED.
- Scrypt cost parameter benchmark on the 8 GB laptop: NOT RUN.
- Windows 11 installation of the browser and Python dependencies, including the coincurve wheel: NOT TESTED.
- The browser utilities are not yet used by the application screens. The production bundle does not include them because nothing imports them yet.

Pending work: wallet creation, encryption, backup, the wallet interface, the scrypt benchmark, Windows verification, and resolution of owner decisions D11 to D22.

### Stage 3 - Blockchain core

Status: NOT STARTED

Deliverables:
- Block structure.
- Transaction structure.
- Genesis configuration generated deterministically from the shared configuration.
- Block hashing.
- Proof of Work.
- Block validation.
- Cumulative-work calculation.
- Chain selection.

Completed work: None.

Pending work: All deliverables above. The genesis configuration has not been generated and depends on the decisions listed under blockers.

### Stage 4 - Local persistence

Status: NOT STARTED

Deliverables:
- JSONL block storage.
- File locking.
- Canonical-chain metadata.
- Startup validation.
- Crash recovery.
- Backup export and import.

Completed work: None.

Pending work: All deliverables above.

### Stage 5 - Three-node network

Status: NOT STARTED

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

Completed work: None.

Pending work: All deliverables above. Requires verification that the three laptops can reach one another on university Wi-Fi.

### Stage 6 - Registration and participants

Status: NOT STARTED

Deliverables:
- Wallet registration.
- SMTP configuration (per-node private configuration).
- OTP verification.
- Role selection.
- On-chain registration.
- Email change.
- Wallet suspension.

Completed work: None.

Pending work: All deliverables above. Requires a selected and working SMTP service.

### Stage 7 - E-waste workflows

Status: NOT STARTED

Deliverables:
- Batch creation.
- Inventory accounting.
- Transfer requests.
- Sender and receiver approvals.
- Rejection and cancellation.
- Expiry.
- Receipt discrepancy.

Completed work: None.

Pending work: All deliverables above.

### Stage 8 - Processing and traceability

Status: NOT STARTED

Deliverables:
- Recycler processing.
- Recovered material creation.
- Material Processor processing.
- Residual accounting.
- Quantity conservation.
- Corrections.
- Traceability reconstruction.
- Completion calculations.

Completed work: None.

Pending work: All deliverables above.

### Stage 9 - API and application

Status: NOT STARTED

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

Completed work: None.

Pending work: All deliverables above.

### Stage 10 - Node management

Status: NOT STARTED

Deliverables:
- Operator authentication.
- Mining controls.
- Peer settings.
- Technical logs.
- Backup management.

Completed work: None.

Pending work: All deliverables above.

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
