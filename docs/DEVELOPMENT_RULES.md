# Development Rules

These rules apply to every future implementation task for the E-Waste Management Blockchain academic project. The master reference is `docs/PROJECT_SPECIFICATION.md`. Where this file and the specification differ, the specification governs until a change is discussed and approved.

## 1. Runtime data

1. No demo, seed, dummy, sample, mock or fabricated data may exist in the normal runtime environment.
2. The real application must start with genuinely empty application state and an empty blockchain state, apart from the agreed genesis configuration.
3. No fake users, wallets, transactions, blocks, inventory, statistics, node statuses or success messages may be shipped or displayed.
4. Test fixtures are permitted only inside isolated temporary test environments with their own storage directories.
5. Test data must never be written to, or mixed with, actual runtime storage on any node.
6. Generated test wallets are disposable and must never be presented as real participants.

## 2. User-facing content

1. No prompt fragments, AI-agent instructions, developer notes, planning notes or implementation instructions may appear anywhere in the user interface.
2. UI wording must be natural, professional, accurate and suitable for real participants and node operators.
3. Every label, button, heading, notification, error message and status message must be reviewed for correctness before a task is considered complete.
4. Status messages must describe the actual state. Do not show "success" before the relevant blockchain transaction is confirmed in the accepted chain.
5. Pending and confirmed activity must be clearly distinguished.
6. Do not display invented node status, peer status, block height or statistics.
7. Interface text is English only in the initial version.
8. Do not present the application as certifying legal compliance, identity verification or environmental safety.

## 3. Scope and simplicity

1. Avoid unnecessary dependencies, features, services, background processes and infrastructure.
2. Do not add a conventional database in the initial version; blockchain storage uses append-only JSONL as specified.
3. Do not add WebSockets unless a specific, tested requirement justifies them.
4. Do not create placeholder pages, components or endpoints that lead nowhere.
5. Avoid duplicate code and abstractions beyond what the task requires.
6. Do not implement features outside the agreed scope without discussing them first.
7. Do not change agreed business rules or architecture without discussion and approval.

## 4. Authority and layering

1. Python blockchain nodes are the authority for validation, business rules, permissions, quantity accounting and confirmed history.
2. Every rule is enforced by the node, never only by React.
3. React is the presentation layer. It may guide users but is never a security or validation boundary.
4. FastAPI is the communication layer. Every input it receives must be validated in Python.
5. Peer assertions, pending pools and local display values are never trusted as authoritative.

## 5. Security and secrets

1. Private keys, wallet passwords, OTP values, SMTP passwords, operator passwords and authentication tokens must never be exposed in the interface, responses, logs or documentation.
2. Never log passwords, private keys, OTPs, SMTP credentials or sensitive tokens.
3. Never store wallet passwords. Never store unencrypted private keys as normal application data.
4. Never send private keys to nodes or other participants.
5. Secrets are supplied through environment configuration, not hardcoded in source code.
6. Use maintained cryptographic libraries. Do not implement cryptographic primitives manually.
7. Validate request sizes and input formats on every endpoint.
8. Rate-limit registration and OTP endpoints.
9. Protect node-management endpoints with operator authentication and authorization, and accept them only from the node's own computer.

## 6. Blockchain integrity

1. Confirmed blockchain history must never be edited, deleted or silently rewritten.
2. Corrections are made only through new signed transactions that reference the original record.
3. Never silently skip invalid records or validation errors. Reject invalid blocks and transactions.
4. Never adopt an invalid chain, even if it claims greater work.
5. Backup imports must be validated in a temporary location before they can be adopted. An older backup must never overwrite a valid newer chain.
6. Quantities are stored and calculated in integer grams. Floating-point arithmetic must not be used for inventory or quantity conservation.
7. Expiry and other time-based rules use consensus block timestamps, never local timers.

## 7. Quality and verification

1. Automated tests are required for each stage, using temporary directories and generated fixtures.
2. A stage is complete only after it has been implemented, reviewed and tested.
3. Do not report a feature as working unless it has been verified. If a verification step cannot be run, state that explicitly.
4. Do not weaken or skip failing tests to produce a green result.
5. UI changes must be checked against the real behaviour of the feature, not only against compilation or type checks.

## 8. Documentation

1. Keep `docs/PROJECT_SPECIFICATION.md` unchanged unless an actual omission or inconsistency is found and reported first.
2. Keep `docs/ARCHITECTURE_OVERVIEW.md` consistent with the specification.
3. Keep `docs/IMPLEMENTATION_STATUS.md` truthful. Never mark functionality as completed before it has been implemented and verified.
4. Do not create planning or analysis documents beyond those agreed for the project.
5. Document the academic limitations in section 24 of the specification in any demonstration material.

## 9. Wallet and key rules

1. Participant private keys are generated, encrypted, stored and used only in the participant's browser.
2. The Python node never generates, receives, stores or requests a participant private key.
3. Only public keys, signed transactions and required public information are sent to FastAPI.
4. Cryptographic libraries are maintained libraries only. The exact library is selected in Stage 2 after checking browser and Windows compatibility.
5. Wallet encryption uses authenticated encryption (AES-GCM preferred) and a password-based KDF (Argon2id or scrypt), with independent random salts and nonces.
6. Node identity private keys stay on their own laptop. They never appear in the shared network configuration, a repository, an API request or a log.
7. Node identity credentials are never used as participant wallet credentials, and participant wallet credentials are never used as node identity credentials.
8. Wallet passwords, operator passwords and SMTP credentials are never stored in plaintext.
9. Generating keys, certificates or genesis data is an implementation activity. It must not be performed during documentation-only tasks.

## 10. Configuration rules

1. The shared network configuration is identical on all three nodes and is versioned.
2. Consensus-critical shared configuration is never silently edited after the network starts.
3. Per-node private configuration is never committed to a repository or shared with other nodes.
4. Certificate fingerprints are verified by the operators out-of-band before they are added to the shared configuration.
5. A new node certificate is never trusted merely because it uses the same node ID.

## 11. Browser and delivery rules

1. Never claim that browser-side signing protects against a malicious node serving modified application code.
2. For the initial demonstration, the designated node operators and the builds they serve are treated as trusted.
3. Do not introduce browser extensions, separate wallet applications or other wallet infrastructure without prior discussion.
4. Wallet portability is provided only by encrypted export and import. Do not create a central wallet server or shared private-key storage.
5. Participant-facing text about wallets must explain that a wallet is kept in the browser used with a given address and must be exported to be used elsewhere.
