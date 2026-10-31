# E-Waste Management Blockchain

## Complete Project Reference Design and Technical Specification

**Project type:** University academic demonstration  
**Deployment:** Three-node private network on university Wi-Fi  
**Frontend:** React  
**Backend and blockchain core:** Python  
**API framework:** FastAPI  
**Consensus:** SHA-256 Proof of Work  
**Digital signatures:** ECDSA secp256k1  
**Local persistence:** Append-only JSONL blockchain storage  
**Initial language:** English

---

# 1. Project overview

The project is a blockchain-based e-waste management and traceability application.

Its purpose is to record the movement, custody, processing and transformation of electronic waste and recovered materials through a chain of registered participants.

The application will support five business roles:

1. Generator
2. Collector
3. Transporter
4. Recycler
5. Material Processor

The blockchain will maintain a verifiable history of:

- Participant registration.
- E-waste batch creation.
- Transfers between participants.
- Transfer approvals and rejections.
- Actual received quantities.
- Transport discrepancies.
- Recycling and material processing.
- Recovered material creation.
- Residual waste accounting.
- Material transfers.
- Corrections to previous records.
- Wallet suspension and other relevant security events.

The main objective is to demonstrate how a small independent blockchain network can provide traceability, transaction validation and tamper-evident records for an e-waste management workflow.

This is an academic demonstration, not a production-certified waste-management or regulatory-compliance system.

# 2. Development principles

The following principles apply throughout development.

## 2.1 No fabricated runtime data

The application must not ship with:

- Fake users.
- Dummy transactions.
- Fabricated blockchain records.
- Fake inventory.
- Fake statistics.
- Sample wallets presented as real participants.
- Artificial success messages.
- Seed or demo data in the normal runtime environment.

Automated tests are still required. Test data must be created in isolated temporary test environments and must never be mixed with actual application data.

## 2.2 Keep the implementation lightweight

- Avoid unnecessary dependencies.
- Avoid duplicate code.
- Avoid unnecessary placeholder pages and components.
- Avoid excessive background services.
- Avoid unnecessary database infrastructure.
- Use a small, clearly structured React application.
- Keep Python node processes lightweight.
- Do not add WebSockets unless actual requirements justify them.
- Do not implement features outside the agreed project scope without discussing them first.

## 2.3 Application quality

The interface must look like a professionally designed human-made application.

- Simple navigation.
- Restrained colours.
- Readable typography.
- Consistent spacing.
- Clear buttons and labels.
- No excessive animations.
- No unnecessary branding or project name.
- English only initially.
- Natural application wording.

Never display developer instructions, prompt fragments, planning notes or technical implementation instructions as user-facing application content.

# 3. Deployment architecture

## 3.1 Selected technology stack

| Layer              | Technology       |
| ------------------ | ---------------- |
| Frontend           | React            |
| Blockchain core    | Python           |
| API                | FastAPI          |
| API communication  | HTTP REST        |
| Hashing            | SHA-256          |
| Digital signatures | ECDSA secp256k1  |
| Consensus          | Proof of Work    |
| Local storage      | JSONL            |
| Operating system   | Windows 11       |
| Initial network    | University Wi-Fi |

Use maintained cryptographic libraries. Do not implement cryptographic primitives manually.

## 3.2 Three independent nodes

There are three team members, each operating one laptop.

Each laptop runs:

1. One independent Python blockchain node.
2. One local FastAPI API process.
3. Its own blockchain storage.
4. Its own node identity and credentials.
5. Its own peer communication service.
6. The React production application served through its FastAPI service.

There is no central shared backend server.

Each node is independently responsible for validating blockchain data and maintaining its local blockchain copy.

## 3.3 Hardware

| Laptop   | RAM   | Processor |
| -------- | ----- | --------- |
| Laptop 1 | 8 GB  | Intel     |
| Laptop 2 | 16 GB | Intel     |
| Laptop 3 | 16 GB | Intel     |

The application must work on the 8 GB laptop.

CPU performance is more relevant than RAM capacity for SHA-256 Proof of Work, so mining difficulty must be benchmarked on all three laptops.

## 3.4 Browser access

Participants should be able to use the application without installing Python or running a blockchain node.

Each node can serve the React production build through FastAPI.

A participant opens the application using the network address of any reachable node.

One laptop can be used as the initial entry point, but it must not become a central server or a single point of failure.

If that laptop is unavailable, participants can open the application through another reachable node.

## 3.5 Network arrangement

Initially, all three nodes communicate over university Wi-Fi.

Each node has a manually configured peer list containing the other two node addresses and ports.

The node must:

- Attempt connections to configured peers.
- Authenticate peers.
- Display peer status.
- Exchange chain information.
- Synchronize missing blocks.
- Continue local operation if a peer is unavailable.
- Retry synchronization when connectivity returns.

Automatic LAN discovery is not required initially.

**Deployment prerequisite:** University Wi-Fi may enable client isolation or firewall restrictions. Verify that all three laptops can communicate directly before implementing the network layer. Use university-approved network configuration and DHCP reservations where appropriate.

# 4. Network identity and genesis configuration

All three nodes must agree on the same blockchain network.

Create one initial network configuration before deployment.

It must include:

- Unique network ID.
- Protocol version.
- Genesis block data.
- Genesis block hash.
- Initial Proof-of-Work difficulty.
- Agreed block and transaction limits.
- Trusted node identities.
- Other protocol parameters required for validation.

The initial protocol version is `1`.

Generate the genesis configuration once and distribute the identical configuration to all three laptops.

Each node must check:

1. Network ID.
2. Protocol compatibility.
3. Genesis block hash.

A node with an incompatible network identity or genesis hash must refuse to join.

Keep the original network configuration backed up separately from ordinary blockchain backups.

# 5. Blockchain and consensus design

## 5.1 Block structure

Each block should contain:

- Block height.
- Previous block hash.
- Timestamp.
- Ordered transactions.
- Nonce.
- Block hash.
- Network identifier or an unambiguous network reference.
- Protocol-compatible block data.

The block hash is calculated using a deterministic canonical serialization of the block header.

Do not hash arbitrary JSON text whose key ordering or formatting can change.

## 5.2 Hashing

Use SHA-256 for:

- Block hashes.
- Transaction IDs.
- Relevant integrity checks.

All nodes must use the same canonical serialization and hashing rules.

## 5.3 Proof of Work

Use a simple fixed-difficulty SHA-256 Proof-of-Work algorithm initially.

- Initial target block time: approximately 10–15 seconds.
- Difficulty: fixed at first.
- Difficulty must be tuned through testing on the slowest laptop.
- No mining reward.
- No cryptocurrency.
- No transaction fees.
- Mining exists only to produce and validate blocks.
- Any of the three node operators can initiate mining.
- No empty blocks unless later required by a clearly defined protocol rule.

The operator should be able to stop mining.

Mining must not create unnecessary memory or CPU consumption. Use a configurable difficulty and test its effect before deployment.

## 5.4 Cumulative-work chain selection

The selected chain is the valid chain with the greatest cumulative Proof of Work.

For every chain, cumulative work is calculated from the work represented by each block's validated difficulty target.

If two valid chains have equal cumulative work:

1. Compare their tip hashes.
2. Select the chain with the lexicographically smaller tip hash.
3. Apply the same rule on every node.

A node must never adopt an invalid chain, even if it claims to have greater work.

## 5.5 Fork handling and chain reorganization

When two nodes mine competing blocks:

1. Nodes independently validate both branches.
2. They compare cumulative work.
3. They apply the deterministic tie-break rule if work is equal.
4. The winning valid chain becomes canonical.
5. A node switching branches rebuilds its confirmed application state from the winning chain.
6. Transactions from the removed branch are re-evaluated.
7. Valid transactions may return to pending.
8. Invalid or conflicting transactions are rejected.

A previously confirmed transaction can return to pending or become invalid after a reorganization.

Do not display permanent finality for a transaction simply because it appeared in a block.

## 5.6 Academic limitation

Three-node PoW is appropriate for a controlled university demonstration, but it is not production-grade Byzantine-fault-tolerant consensus.

A malicious or compromised node could disrupt the network. The project must document this limitation honestly.

# 6. Block and transaction validation

Every node independently validates incoming transactions and blocks.

The frontend is never trusted to enforce blockchain rules.

## 6.1 Block validation

Check:

- Correct network ID.
- Correct protocol version.
- Previous block hash.
- Block hash.
- Proof of Work.
- Block height.
- Timestamp rules.
- Transaction ordering.
- Transaction uniqueness.
- Transaction signatures.
- Transaction business rules.
- Block-size limits.
- Transaction-count limits.
- State transitions.

Reject invalid blocks. Never silently skip validation errors.

## 6.2 Timestamp rules

- Store timestamps in UTC.
- Use a consistent ISO 8601 representation.
- Require a block timestamp to be greater than the median timestamp of the preceding 11 blocks.
- Restrict timestamp advancement relative to the previous block.
- Use the same consensus rules on all nodes.

A local node may apply an additional future-time sanity check before relaying a block. Such a local clock check must not create inconsistent consensus acceptance between nodes.

## 6.3 Initial limits

Use the following conservative starting limits:

| Limit                         | Initial value  |
| ----------------------------- | -------------- |
| Transactions per block        | 100            |
| Maximum serialized block size | 1 MB           |
| General transaction payload   | 16 KB          |
| E-waste description           | 500 characters |
| Processing description        | 500 characters |

These limits may be adjusted after integration and performance testing.

Reject oversized requests before accepting them into the pending pool.

# 7. Transaction design

## 7.1 Transaction identity

Every transaction receives a unique ID derived from its canonical serialized content.

The signed content must include all fields that affect its meaning.

Nodes must reject:

- Duplicate transaction IDs.
- Invalid signatures.
- Invalid participant permissions.
- Invalid quantities.
- Invalid state transitions.
- Conflicting transactions.
- Transactions referencing nonexistent or ineligible records.

## 7.2 Transaction ordering

Use deterministic ordering.

Initial rule:

1. Sort by transaction timestamp.
2. If timestamps are equal, sort by transaction ID.

Validate transactions sequentially against the state resulting from previously accepted transactions in that block.

If transactions conflict, only the first valid transaction in this deterministic ordering may be applied.

## 7.3 Pending pool

Each node maintains a local pending transaction pool.

The pool is not itself the blockchain.

A node must independently validate a transaction before accepting it into its local pool.

When a block is accepted or the chain is reorganized, the pending pool must be reconciled against the new canonical state.

A peer's pending pool is never trusted as authoritative.

## 7.4 Transaction states

Use:

- `PENDING`
- `CONFIRMED`
- `REJECTED`
- `CANCELLED`

A transaction becomes confirmed when included in the currently accepted valid chain.

After a chain reorganization, the transaction status must be recalculated.

# 8. Digital signatures and wallets

## 8.1 Wallet identity

Each participant wallet has:

- A public/private key pair.
- A blockchain wallet address.
- An encrypted local private-key file.

Use ECDSA secp256k1 signatures.

Every business transaction requiring participant authorization must be signed by the relevant participant wallet.

## 8.2 Local encryption

- Derive encryption keys from wallet passwords using a maintained password-based key derivation function such as Argon2id or scrypt.
- Use authenticated encryption such as AES-GCM.
- Generate a random salt and nonce.
- Never store the wallet password.
- Never store an unencrypted private key as normal application data.
- Never send private keys to nodes or other participants.

## 8.3 Wallet storage and signing

The participant's wallet should be managed locally in the browser environment.

The private key is decrypted only when the participant unlocks the wallet.

Signing occurs locally. Only the signed transaction is submitted to a node.

The Python node verifies the signature using the public key.

## 8.4 Wallet inactivity lock

Automatically lock the wallet after 15 minutes of inactivity.

The participant must unlock it again before signing additional transactions.

## 8.5 Wallet backup and restoration

Provide:

- Encrypted wallet backup.
- Wallet export.
- Wallet import and restoration.

A successful restore must reproduce the same wallet identity.

The backup requires the wallet password.

If the participant loses both their usable private-key backup and recovery credentials, the wallet cannot be recovered. There is no administrator backdoor.

## 8.6 Wallet suspension

A participant can suspend their own wallet if they suspect compromise.

- No node-operator approval is needed.
- The suspension is recorded on-chain.
- Historical records remain.
- A suspended wallet cannot initiate new business transactions.
- A participant can create and register a new wallet.

Assets in the old wallet can move only through valid transactions.

# 9. Participant registration

## 9.1 Business roles

Each wallet may register for exactly one role:

1. Generator.
2. Collector.
3. Transporter.
4. Recycler.
5. Material Processor.

The role is immutable after registration.

A person could create multiple wallets, so this rule does not prove that one real-world person has only one role.

## 9.2 Registration process

1. Participant creates a wallet.
2. Participant requests a business role.
3. Participant provides contact information.
4. Application sends an email OTP.
5. Participant verifies the OTP.
6. A signed verification attestation is created.
7. Participant registration is recorded on-chain.

Registration must remain incomplete until email verification succeeds.

## 9.3 On-chain information

Record only:

- Wallet address.
- Requested and approved business role.
- Verification status.
- Registration timestamp.

Do not store email addresses, phone numbers or OTPs on-chain.

Email verification demonstrates access to an email account. It does not prove real-world identity, business licensing or regulatory authorization.

## 9.4 Email delivery

Use SMTP.

- Configure SMTP through environment settings.
- Do not hardcode credentials.
- Do not log OTPs.
- Do not put contact information or OTPs on-chain.
- If SMTP fails, registration remains incomplete.
- Display a genuine delivery error.
- Allow a later resend.

Initial OTP settings:

| Setting                 | Value                |
| ----------------------- | -------------------- |
| OTP length              | 6 digits             |
| Validity                | 10 minutes           |
| Maximum failed attempts | 5                    |
| Resend interval         | 60 seconds           |
| Resend limit            | 3 per hour per email |

Apply rate limits to registration and OTP endpoints.

## 9.5 Verification authority

There is no central administrator or participant-voting process.

Any of the three configured, authenticated nodes may issue an email-verification attestation after successful OTP verification.

Other nodes validate that attestation against the trusted node identities included in the network configuration.

This is a limited trust arrangement for the academic project; it must not be described as independent real-world identity verification.

## 9.6 Email changes

A participant can change their email after verifying the new address.

If the old email is inaccessible:

1. The participant signs an email-change request using their wallet.
2. The new email is verified.
3. The update is accepted.
4. The email itself remains off-chain.

A participant cannot update another participant's email.

# 10. E-waste batch creation

Only a registered Generator can create an original e-waste batch.

Record:

- Automatically generated batch ID.
- Free-text e-waste description.
- Quantity.
- Creation timestamp.
- Generator wallet address.
- Digital signature.

There are no predefined e-waste categories.

## 10.1 Quantity precision

- Enter quantities in kilograms.
- Maximum input precision: three decimal places.
- Convert kilograms to integer grams.
- Store and calculate all quantities in integer grams.
- Display quantities in kilograms.

Never use floating-point arithmetic for inventory balances or quantity conservation.

# 11. Custody transfer workflow

## 11.1 Permitted role transitions

| Sender role        | Permitted receiver role                    |
| ------------------ | ------------------------------------------ |
| Generator          | Collector                                  |
| Collector          | Transporter                                |
| Transporter        | Recycler                                   |
| Recycler           | Material Processor                         |
| Material Processor | No further transfer in the initial version |

A sender cannot skip a role in the workflow.

The sender and receiver must be different participants.

## 11.2 Transfer request

The sender:

1. Selects a batch or material.
2. Specifies a full or partial quantity.
3. Selects an eligible receiver.
4. Signs the transfer request.

The node verifies available quantity and role permissions.

The declared quantity is reserved when the transfer request is confirmed on-chain.

Reserved quantity cannot be transferred or processed again.

## 11.3 Receiver response

The receiver can:

- Accept the transfer.
- Reject the transfer with a reason.

Acceptance requires a receiver signature and records the actual quantity received.

Both sender and receiver must digitally approve the transfer.

## 11.4 Actual received quantity

The actual received quantity cannot exceed the declared quantity.

If actual quantity is lower:

- A reason is mandatory.
- The discrepancy is recorded on-chain.
- The sender loses the declared quantity.
- The receiver receives the actual quantity.
- The difference is recorded as a transport discrepancy or loss.

Example:

Declared quantity: 100 kg  
Actual received quantity: 95 kg  
Recorded discrepancy: 5 kg

The 5 kg must remain accounted for as a discrepancy. It cannot silently disappear.

A zero-quantity receipt may be accepted only as a fully documented loss event with a reason and both required signatures.

## 11.5 Cancellation and rejection

- The sender may cancel a pending transfer before receiver acceptance.
- The receiver may reject a pending transfer with a reason.
- Cancellation or rejection releases the reserved quantity.
- Rejected transfers do not move ownership.
- Once a transfer has been accepted and confirmed, it cannot be cancelled by editing history.

## 11.6 Expiry

A transfer expires after 48 hours if the receiver does not respond.

Expiry must be deterministic across nodes.

- Record the request time and expiry time.
- Apply expiry through blockchain state-transition rules.
- Use the consensus timestamp of valid blocks.
- Release reserved quantity when expiry is applied.

If no blocks are produced, expiry may not be recorded immediately. It is applied when a later valid block advances the chain timestamp sufficiently.

The system must not use separate local timers to make different nodes reach different consensus results.

# 12. Processing and recovered materials

Recycler and Material Processor can process eligible inventory according to role permissions.

## 12.1 Processing record

Record:

- Input batch or material ID.
- Input quantity.
- All output materials and quantities.
- Residual waste quantity.
- Optional processing method description.
- Timestamp.
- Participant wallet.
- Digital signature.

## 12.2 Quantity conservation

Every processing operation must satisfy:

**Input quantity = Sum of all outputs + Residual waste**

All quantities are represented as integer grams.

A processing operation cannot consume more than the participant's available unreserved inventory.

## 12.3 Multiple outputs

One processing operation can produce multiple recovered materials.

Each recovered material receives a unique material ID.

Each output inherits provenance links to:

- Its input batch or material.
- The processing operation.
- The processing participant.
- Earlier history of its source.

Residual waste is explicitly recorded.

## 12.4 Partial processing

Partial processing is allowed.

Any unprocessed input quantity remains in the participant's inventory.

It must not be marked as completed.

## 12.5 Corrections

Confirmed records are immutable.

A correction is a new signed transaction referencing the original record.

It must include:

- Original record reference.
- Correction explanation.
- Corrected or compensating information.
- Participant signature.

Never directly edit or delete confirmed blockchain records.

# 13. Quantity accounting and lifecycle

Use an inventory-lot model.

Each batch or material has a traceable quantity balance.

For every inventory item, calculate:

- Total quantity received or created.
- Quantity reserved for pending transfers.
- Quantity reserved for pending processing, if processing is modelled as a pending operation.
- Available quantity.
- Quantity transferred.
- Quantity processed.
- Quantity accounted as discrepancy or residual.
- Remaining quantity.

All balances are derived from blockchain records, not manually editable frontend values.

## 13.1 Transfer accounting

A transfer request reserves quantity.

When accepted:

- Deduct the declared quantity from the sender.
- Credit the receiver with the actual quantity.
- Record any difference as a discrepancy/loss.

When cancelled, rejected or expired:

- Release the reservation.
- Do not change ownership.

## 13.2 Processing accounting

When processing is confirmed:

- Deduct the consumed input quantity.
- Create output material quantities.
- Record residual waste.
- Preserve any unprocessed remainder.

## 13.3 Batch completion

An original e-waste batch is completed when:

- All original e-waste quantity has been processed or otherwise explicitly accounted for.
- No original e-waste quantity remains available at any participant.
- No relevant pending operation remains.

A transfer alone does not complete a batch because it changes custody, not the existence of the e-waste.

Recovered material outputs have their own lifecycle and do not keep the original e-waste batch active.

## 13.4 Material completion

A material is completed when:

- Its remaining quantity is zero.
- No relevant pending operation remains.

In the initial version, Material Processor outputs cannot be transferred to another business role. Further processing is permitted.

# 14. Traceability and access control

## 14.1 Complete traceability

The application must reconstruct history from accepted blockchain records.

For a batch, show:

- Original Generator.
- Batch creation.
- Custody transfers.
- Sender and receiver approvals.
- Receipt quantities.
- Discrepancies.
- Recycler processing.
- Recovered material outputs.
- Residual waste.
- Current ownership and quantity.

For recovered materials, show:

- Source processing operation.
- Parent batch or material.
- Quantity created.
- Subsequent transfers, if permitted.
- Further processing.
- Outputs and residuals.
- Current owner and remaining quantity.

## 14.2 Historical involvement

Use historical involvement as the access rule.

- Participants involved in a batch or material retain read-only access to relevant history.
- A participant does not lose access to their own historical involvement after transferring all quantity.
- A participant who was never involved cannot access private participant-level traceability.
- Material outputs inherit provenance links from their source operation.

## 14.3 Privacy limitation

The blockchain is replicated across all nodes. Therefore, hiding a record in the React interface is not equivalent to making that record confidential from node operators.

The initial academic design should store minimal personal information on-chain and enforce application-level participant visibility.

Do not claim that the system provides full data confidentiality from node operators.

# 15. Participant application

The participant interface should provide only the pages required by the agreed workflows.

## 15.1 Core areas

- Wallet.
- Registration.
- Dashboard.
- Batches.
- Transfers.
- Materials.
- Processing.
- History.
- Notifications.

Show role-appropriate actions.

For example:

- Generator: create and transfer batches.
- Collector: receive eligible batches and transfer to Transporter.
- Transporter: receive and transfer to Recycler.
- Recycler: receive e-waste, process it and transfer recovered materials.
- Material Processor: receive recovered materials and process them.

Do not show actions that a participant's role cannot perform.

## 15.2 Dashboard information

Display calculated information such as:

- Available inventory.
- Reserved inventory.
- Received quantity.
- Transferred quantity.
- Processed quantity.
- Pending actions.
- Relevant history.

All figures must be calculated from confirmed blockchain state and clearly distinguish pending from confirmed activity.

## 15.3 Traceability

Participants see only traceability records for batches and materials in which they have been involved.

## 15.4 Network status

All participants can see:

- Node online/offline status.
- Synchronization status.
- Latest accepted block height.
- Number of reachable nodes.

Do not display invented node status or fabricated statistics.

# 16. Notifications

Use in-app notifications only.

No email or SMS business notifications are required.

Notify participants about:

- Pending transfer approvals.
- Accepted or rejected transfers.
- Transfer expiry.
- Transaction confirmation.
- Relevant ownership changes.
- Node offline and reconnection events.

Notifications must be derived from actual application or blockchain events.

# 17. Node operators

There are three designated node operators.

Each operator can manage their own node.

## 17.1 Management functions

- Start and stop their node.
- Start and stop mining.
- View technical logs.
- Manage peer settings.
- Export blockchain backups.
- Import validated blockchain backups.

Ordinary participants cannot access node-management functions.

## 17.2 Operator authentication

- Use a separate operator password for each node.
- Do not share operator passwords across laptops.
- Store password verifiers securely, never plaintext passwords.
- Expire operator sessions after inactivity.
- Protect management endpoints with authentication and authorization.

Operator access does not allow anyone to edit confirmed blockchain records or bypass validation.

## 17.3 Technical logs

Operators can view:

- Peer connection failures.
- Invalid block events.
- Synchronization problems.
- Mining errors.
- Storage errors.
- API errors.

Never log:

- Wallet passwords.
- Private keys.
- OTP values.
- SMTP passwords.
- Sensitive authentication tokens.

# 18. Peer authentication and communication

Each node receives:

- Unique node identity.
- Its own cryptographic credentials.
- Configured peer addresses.
- Trusted network configuration.

Use encrypted authenticated node-to-node communication, preferably HTTPS with mutual TLS and pinned node certificates.

Each node must:

- Authenticate the peer.
- Check network ID.
- Check protocol version.
- Validate incoming blocks.
- Validate incoming transactions.
- Reject unknown or incompatible peers.

Node credentials are separate from participant wallet credentials.

Private keys for participant wallets are never sent between nodes.

# 19. API design

Use FastAPI to provide a small, organized REST API.

The frontend connects to the node selected by the participant.

## 19.1 Participant API groups

- Wallet creation.
- Wallet unlock and lock.
- Wallet backup and restore.
- Registration.
- OTP request and verification.
- Participant profile and email change.
- Batch creation and history.
- Transfer creation.
- Transfer acceptance.
- Transfer rejection.
- Transfer cancellation.
- Inventory.
- Material details.
- Processing operations.
- Traceability.
- Transaction status.
- Notifications.
- Network status.

## 19.2 Node-management API groups

- Operator authentication.
- Node start/stop status.
- Mining control.
- Peer configuration.
- Technical logs.
- Backup export.
- Backup import.

## 19.3 Peer API groups

- Peer authentication.
- Node information.
- Network compatibility.
- Latest block information.
- Cumulative-work information.
- Block download.
- Block validation and acceptance.
- Transaction announcement.
- Chain synchronization.
- Peer health status.

All inputs must be validated by Python.

The frontend is not a security boundary.

## 19.4 Communication approach

Use HTTP REST initially.

Do not add WebSockets at the start.

If testing later demonstrates that polling is insufficient for mining progress or incoming transaction updates, WebSockets may be added for those specific needs.

# 20. Local persistence and crash recovery

## 20.1 JSONL storage

Each node maintains its own local blockchain data.

Use append-only JSONL records for accepted blocks.

Do not use a conventional database in the initial version.

## 20.2 Reorganization-safe storage

Store validated blocks so that competing branches can be retained during fork resolution.

Maintain canonical-chain selection separately from the append-only block records.

A separate small metadata file can identify the current canonical tip.

Do not rewrite historical block records simply because a fork occurs.

## 20.3 Write safety

- Permit only one local writer at a time.
- Use file locking.
- Flush completed writes to disk.
- Use safe atomic replacement for canonical-tip metadata.
- On startup, validate stored records.
- Preserve original files during recovery.
- Recover an incomplete final write only through a documented procedure.
- Stop normal operation if a complete record is malformed or a block fails validation.
- Never silently skip invalid records.

## 20.4 Backup and restore

Node operators can export and import blockchain backups.

An import must:

1. Be written to a temporary location.
2. Be checked for network identity.
3. Be checked for valid block structure and signatures.
4. Be checked for valid Proof of Work.
5. Be checked for valid chain history.
6. Be compared with the active chain.
7. Be made eligible for adoption only after validation.

An older backup must never blindly overwrite a valid newer chain.

# 21. Windows 11 installation and deployment

Provide a clear setup procedure for all three laptops.

Each installation must have:

- Python environment.
- Required Python dependencies.
- React production build.
- Unique node identity.
- Unique local data directory.
- Unique listening port.
- Operator credentials.
- Configured peer addresses.
- Trusted network configuration.

Configure Windows Firewall to allow only the necessary application and peer ports on the university network.

Do not expose the application to the public internet during this project stage.

Test:

1. Each node starts independently.
2. All three nodes can reach one another.
3. Participants can open the application through a browser.
4. The application works through more than one node address.
5. A node can restart and reload its local chain.
6. A disconnected node can synchronize after reconnecting.
7. A node outage is shown honestly in the interface.

If possible, use a fourth device to test participant browser access.

# 22. Security requirements

The system must:

- Validate every signature.
- Validate every business operation on the node.
- Enforce role permissions on the node.
- Prevent duplicate transaction processing.
- Prevent double spending through reservations.
- Authenticate peer nodes.
- Protect node-to-node communication.
- Encrypt local wallet keys.
- Protect operator management endpoints.
- Rate-limit OTP and registration endpoints.
- Validate request sizes and input formats.
- Keep secrets outside source code.
- Never log passwords, private keys or OTPs.
- Reject invalid blocks and transactions.
- Preserve immutable confirmed history.

# 23. Testing strategy

Automated tests are required throughout development.

Tests must use temporary directories, isolated generated wallets and controlled test fixtures.

They must not populate the real runtime blockchain.

## 23.1 Cryptography and wallets

Test:

- Wallet creation.
- Password encryption.
- Wallet unlock.
- Incorrect password rejection.
- Signature generation.
- Signature verification.
- Invalid signature rejection.
- Backup and restore.
- Same wallet identity after restore.
- Wallet lock after inactivity.

## 23.2 Registration

Test:

- OTP delivery success and failure.
- OTP expiry.
- Incorrect OTP.
- Attempt limits.
- Resend limits.
- Registration only after verification.
- One role per wallet.
- Role immutability.
- Wallet suspension.
- Email change.

## 23.3 Business rules

Test:

- Batch creation.
- Quantity precision.
- Full transfer.
- Partial transfer.
- Invalid role transitions.
- Self-transfer rejection.
- Sender and receiver signatures.
- Transfer reservations.
- Cancellation.
- Rejection.
- Expiry.
- Actual received quantity.
- Discrepancy accounting.
- Processing quantity conservation.
- Multiple outputs.
- Residual accounting.
- Batch completion.
- Material completion.
- Correction records.
- Traceability access.

## 23.4 Blockchain and network

Test:

- Block hashing.
- Proof of Work.
- Block validation.
- Transaction ordering.
- Duplicate rejection.
- Invalid block rejection.
- Peer authentication.
- Synchronization.
- Competing blocks.
- Cumulative-work selection.
- Equal-work tie-breaking.
- Chain reorganization.
- Pending-pool reconciliation.
- Crash recovery.
- Backup import validation.

## 23.5 Integration

Test all three nodes on the actual laptops.

Verify that each node independently reaches the same canonical chain and calculates the same business state.

Test a node outage and reconnection.

Test a browser participant using another reachable node address.

# 24. Academic-project limitations

The project documentation and demonstration must state the following:

1. Email verification proves access to an email account, not real-world identity or licensing.
2. A person can create multiple wallets.
3. Three-node PoW is not production-grade Byzantine-fault-tolerant consensus.
4. A compromised node can disrupt a small demonstration network.
5. University Wi-Fi and firewall policies affect peer connectivity.
6. The blockchain does not certify legal compliance or the environmental safety of processing.
7. Lost private keys without backups cannot be recovered by an administrator.
8. Email OTP delivery depends on an operational SMTP service.
9. Participant visibility restrictions in the interface do not make replicated blockchain data confidential from node operators.
10. The system is designed for a controlled academic demonstration, not public production deployment.

# 25. Implementation roadmap

Build the project in small stages.

Each stage should be completed, reviewed and tested before starting the next.

## Stage 1 — Project foundation

- Create project structure.
- Set up React.
- Set up Python environment.
- Set up FastAPI.
- Define configuration management.
- Define code quality and test structure.

## Stage 2 — Cryptographic foundation

- SHA-256 utilities.
- Canonical serialization.
- ECDSA secp256k1 signing and verification.
- Wallet creation.
- Encrypted wallet storage.
- Wallet backup and restore.

## Stage 3 — Blockchain core

- Block structure.
- Transaction structure.
- Genesis configuration.
- Block hashing.
- Proof of Work.
- Block validation.
- Cumulative-work calculation.
- Chain selection.

## Stage 4 — Local persistence

- JSONL block storage.
- File locking.
- Canonical-chain metadata.
- Startup validation.
- Crash recovery.
- Backup export and import.

## Stage 5 — Three-node network

- Node identities.
- Peer authentication.
- Peer configuration.
- Transaction announcement.
- Block exchange.
- Chain synchronization.
- Fork handling.
- Reorganization.
- Network status.

## Stage 6 — Registration and participants

- Wallet registration.
- SMTP configuration.
- OTP verification.
- Role selection.
- On-chain registration.
- Email change.
- Wallet suspension.

## Stage 7 — E-waste workflows

- Batch creation.
- Inventory accounting.
- Transfer requests.
- Sender and receiver approvals.
- Rejection and cancellation.
- Expiry.
- Receipt discrepancy.

## Stage 8 — Processing and traceability

- Recycler processing.
- Recovered material creation.
- Material Processor processing.
- Residual accounting.
- Quantity conservation.
- Corrections.
- Traceability reconstruction.
- Completion calculations.

## Stage 9 — API and application

- Participant REST APIs.
- Operator REST APIs.
- Peer REST APIs.
- React participant interface.
- Wallet interaction.
- Role-based navigation.
- Dashboards.
- Notifications.
- Traceability views.
- Network status.

## Stage 10 — Node management

- Operator authentication.
- Mining controls.
- Peer settings.
- Technical logs.
- Backup management.

## Stage 11 — Integration and deployment

- Unit tests.
- Integration tests.
- Security tests.
- Three-laptop network tests.
- Windows deployment procedure.
- Browser access tests.
- Restart and recovery tests.
- Performance tuning.

---

# 26. Final project acceptance criteria

The academic demonstration is considered ready when:

1. All three laptops can run independent nodes.
2. All nodes share the same genesis configuration.
3. Nodes authenticate one another.
4. Nodes can exchange and validate blocks.
5. Nodes converge on the same valid canonical chain.
6. Forks can be resolved using the agreed rules.
7. A participant can create and restore a wallet.
8. Email verification works with a real SMTP service.
9. Participants can register for one immutable role.
10. A Generator can create an e-waste batch.
11. Eligible participants can transfer custody with both signatures.
12. Reservations prevent double spending.
13. Receipt discrepancies are recorded correctly.
14. Recycler and Material Processor can perform valid processing.
15. Every processing operation conserves quantity.
16. Recovered materials have unique IDs and traceable provenance.
17. Participants can see permitted history and inventory.
18. Invalid operations are rejected by the Python nodes.
19. A node can restart and recover its blockchain.
20. A disconnected node can synchronize after reconnecting.
21. Participants can use the application through a browser without running a node.
22. Node-management functions are restricted to node operators.
23. No fabricated runtime records or fake success messages are present.

---

# 27. Final architectural principle

**The blockchain nodes are the authority for transaction validity, ownership, quantity accounting, participant permissions and confirmed history.**

React is the user interface. FastAPI is the communication layer. Python performs validation, business-rule enforcement, cryptographic verification, block creation and peer synchronization.

No frontend action, local display value or peer assertion can override the rules independently enforced by the blockchain nodes.

**This document is the master reference for the E-Waste Management Blockchain academic project. All implementation work must follow it unless a technical limitation is identified, explained and agreed upon.**

---

# Implementation Architecture Clarifications

This section records implementation decisions made after the original specification to resolve ambiguities that would otherwise block implementation.

- Sections 1 to 27 above are the original requirements and are unchanged.
- Each clarification below is labelled as a clarification and cross-referenced to the original section it refines.
- A clarification refines an original requirement; it does not replace or weaken it. Where a clarification adds a stricter rule, the stricter rule applies.
- Anything not covered here remains governed by sections 1 to 27.

## C1. Participant wallet architecture (refines sections 8.1 to 8.5)

Browser responsibilities:

- Generate participant ECDSA secp256k1 key pairs using a maintained cryptographic library and a cryptographically secure random-number source.
- Encrypt the participant's private key locally using a key derived from the wallet password.
- Store only encrypted wallet material in browser-local storage.
- Decrypt the private key locally only when the participant unlocks the wallet to sign.
- Sign transactions locally.
- Submit to FastAPI only the public key, the signed transaction and the required public information.

Python node responsibilities:

- Receive signed transactions.
- Verify participant signatures using public keys.
- Validate permissions, roles, quantities, state transitions and all other business rules.
- Never generate, receive, store or request participant private keys.

Encryption:

- Use authenticated encryption, preferably AES-GCM.
- Use a maintained password-based key derivation function, Argon2id or scrypt, as required by section 8.2.
- Generate independent random salts and nonces.
- Never store wallet passwords or plaintext private keys.

Library selection:

- The exact maintained library and compatible versions are deferred to Stage 2 (section 25), to be checked for browser and Windows compatibility.
- No cryptographic primitive is implemented manually.

Relationship to section 8.3: the wallet is managed in the browser, and the node verifies signatures only. This clarification makes that split explicit.

## C2. Credential types (refines sections 8, 17.2 and 18)

The system uses distinct credentials. None may be substituted for another.

| Credential | Owner | Where it lives | Purpose |
| --- | --- | --- | --- |
| Participant wallet private key | Participant | Browser, encrypted | Signs business transactions |
| Participant wallet password | Participant | Participant's memory only | Unlocks the wallet; never stored |
| Node identity private key | Node operator | That operator's laptop only | Identifies the node to peers during mutual TLS |
| Node TLS certificate and fingerprint | Node operator | Shared as public data | Pinned by peers in the shared network configuration |
| Operator password | Node operator | Node, as a password verifier only | Authorises node-management functions (section 17.2) |
| SMTP credentials | Node operator | Per-node private configuration | Sends OTP emails (section 9.4) |

Node identity credentials are separate from participant wallet credentials, as required by section 18.

## C3. Node identity and certificate architecture (refines sections 3.2, 4 and 18)

Each node has:

- A unique node ID.
- A unique node identity private key.
- A unique TLS certificate.
- A unique certificate SHA-256 fingerprint.
- A unique local node configuration.

Peer authentication uses mutual TLS with certificate fingerprint pinning. A peer is accepted only when both sides authenticate and the presented certificate's fingerprint matches the trusted fingerprint recorded for that node ID in the shared network configuration.

Initial manual provisioning:

1. Each operator generates their node identity key and certificate on their own laptop.
2. The private identity key stays on that laptop.
3. Public certificates are exchanged among the three operators through a secure channel agreed by the operators.
4. Each operator calculates the SHA-256 fingerprint of each certificate, and the three operators verify the values match.
5. Trusted node IDs and fingerprints are added to the shared network configuration.
6. The identical trusted configuration is distributed to all three laptops.
7. Mutual authentication is verified before any peer communication is accepted.

Certificate renewal:

- A replacement certificate is verified using the same fingerprint procedure.
- Renewal requires an agreed update to the shared trusted configuration, distributed identically to all three nodes.
- A new certificate is never trusted merely because it presents the same node ID.

No public certificate authority and no central certificate server are used.

## C4. Shared and per-node configuration (refines sections 4 and 9.4)

Shared network configuration: identical on all three nodes and versioned. It contains:

- Network ID.
- Protocol version (initially `1`, section 4).
- Deterministic genesis parameters and the genesis block hash.
- Initial Proof of Work difficulty and other consensus parameters.
- Block and transaction limits (section 6.3).
- Trusted node IDs.
- Trusted node certificate fingerprints.
- Other consensus-critical protocol parameters.

Genesis block data is generated deterministically from the shared configuration. All nodes calculate and verify the same genesis hash.

Once the network has started, consensus-critical configuration must not be silently changed. A change that alters network identity or genesis compatibility requires a deliberately new network configuration and network. Trusted-fingerprint renewal follows C3.

Per-node private configuration: unique to each laptop, never shared and never placed in any repository. It contains:

- Local node ID.
- Listening host and port.
- Local data directory.
- Paths to the local node identity key and certificate.
- Configured peer addresses and ports.
- Operator authentication configuration.
- SMTP settings.
- Other non-shared operational settings.

Settings that must be identical on all three nodes: network ID, protocol version, genesis data and hash, consensus parameters, limits, trusted node IDs and trusted fingerprints.

Settings that must be unique per node: node ID, node identity key and certificate, local data directory, listening port, and the operator's own operator password and SMTP configuration. Each node's peer list contains the other two nodes.

Secrets (private keys, passwords, SMTP credentials) never appear in the shared network configuration.

## C5. Browser origin and wallet portability (refines sections 3.4 and 8.3)

Browser-local storage such as IndexedDB is scoped to an origin, and an origin includes the address and port. Different node addresses or ports are different origins.

Consequently, opening the application through Laptop A and later through Laptop B does not guarantee that the same browser wallet storage is available.

Retained requirement: a participant can use the application through any reachable node (section 3.4).

Mitigation:

- Encrypted wallet export creates an encrypted wallet file.
- Encrypted wallet import requires the wallet password.
- A restored wallet reproduces the same public key and wallet address.
- The plaintext private key is never transmitted to a node.
- No central wallet server and no shared private-key storage are introduced.

Participant-facing text about wallets must state that a wallet is kept in the browser used with a given address, and that it must be exported to be used elsewhere.

## C6. Frontend delivery trust (refines sections 3.4, 8.3, 22 and 24)

The React application is served by a node. A malicious or compromised node operator could serve modified JavaScript that captures wallet information, including the wallet password or decrypted key material.

Browser-side key generation and local signing keep participant private keys out of the nodes, so an honest node never needs custody of them. These measures do not protect against malicious frontend code.

For the initial academic demonstration:

- The three designated node operators and the application builds they serve are treated as trusted.
- Private keys are never included in API requests.
- No claim is made that browser-side signing protects against a malicious serving node.
- No browser extensions, separate wallet applications or additional infrastructure are added to the initial scope.

Any stronger frontend-delivery protection must be discussed separately before being added.

## C7. Development and deployment environments (refines sections 3.1 and 21)

- The Linux environment used for code generation and development is not the deployment target.
- The deployment target remains Windows 11 on all three laptops.
- Code and dependencies must be portable Python and React, selected for installation and operation on the actual Windows laptops.
- Deployment validation (section 21 and section 23.5) must occur on all three Windows laptops. Success in the development environment does not count as deployment validation.

## C8. Additional academic limitations (supplements section 24)

11. Participant wallets are scoped to the browser origin used; they move between node addresses only through encrypted export and import.
12. A malicious or compromised node operator could serve modified application code that captures wallet information (C6).
13. Peer authentication by fingerprint pinning depends on operators verifying certificate fingerprints correctly. A wrongly verified certificate weakens peer authentication.

## C9. Decisions still open

- Exact cryptographic libraries and versions (Stage 2, C1).
- Secure channel used for exchanging public certificates (C3, step 3).
- Procedure and timing for activating a trusted-configuration update during certificate renewal, including whether the old fingerprint remains valid during transition (C3).
- Whether trusted-node changes affect the acceptance of previously issued email-verification attestations (sections 9.5 and C4).
- SMTP provider (section 9.4).
- Difficulty tuning on the slowest laptop (section 5.3).
