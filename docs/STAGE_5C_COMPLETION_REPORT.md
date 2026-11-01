# Stage 5C Completion Report

Status: implementation completed; automated verification passed in the Linux development environment. Windows 11 and the real three-laptop test on university Wi-Fi are not performed.

## Scope delivered

- In-memory pending transaction pool (`app/node/pending_pool.py`):
  - Capacity of 1000 pending transactions; new entries are refused, not evicted, when full.
  - Admission reuses the Stage 3 transaction validation and a size limit of the configured payload maximum plus a fixed envelope allowance.
  - Admission states: `accepted`, `known` (already pending), `confirmed` (already in the canonical chain), `rejected` (invalid), `unavailable` (pool full).
  - The confirmed set is recomputed whenever the canonical tip changes, under the storage lock, so a transaction confirmed by a newly accepted block cannot be admitted in the gap before reconciliation.
  - Reconciliation removes transactions confirmed on the canonical chain and re-admits transactions removed by a reorganization.
  - Deterministic ordering by timestamp, then transaction ID.
  - Eligible-transaction selection for block construction, bounded by the configured transaction-count limit and a block-size budget that reserves an allowance for block overhead.
- Transaction relay (`app/node/transaction_relay.py`):
  - Local submissions and received announcements are admitted once; only newly accepted transactions are re-announced, excluding the origin peer, which prevents loops.
  - Outbound sends run on a bounded pool of four workers, with two attempts separated by 0.5 seconds. Request handlers never wait for outbound sends.
  - When a peer connects, pending transactions are sent to it.
- Peer endpoint `POST /peer/transactions` (`app/node/peer_server.py`): requires the existing mutual TLS client certificate, enforces a size limit, parses strict JSON, and returns the admission state.
- Synchronizer integration: after each batch, the synchronizer reconciles the pool with the removed transactions; startup builds the pool from the restored chain.

## Verification

- `tests/test_transaction_pool.py`: 13 tests, all passing. Covers admission (valid, forged signature, incorrect transaction ID, oversized payload, duplicate, confirmed, capacity), ordering, reconciliation after confirmation, re-admission after reorganization, non-canonical branches, restart reconciliation, and eligible selection under the count limit.
- `tests/test_transaction_propagation.py`: 8 tests, all passing, using temporary directories and real mutual TLS between local listeners. Covers two-node delivery, delivery across an intermediate peer (three nodes, with the first and third not directly connected), duplicate suppression, delivery after a peer comes online, rejection of a client without a trusted certificate, rejection of a transaction from another network, non-propagation of an invalid transaction, and removal of a confirmed transaction.
- Full backend suite (Stages 3, 4, 5A, 5B, 5C, health and configuration): 283 tests passed.

## Defects found and fixed during verification

- The pool's confirmed set was refreshed only during reconciliation, so a transaction confirmed by a newly accepted block could be admitted until the next reconciliation. The set now refreshes whenever the canonical tip changes.
- Test-side fixes: a node with no trusted peers cannot start its listener (empty trust bundle), and the untrusted-client test must not import a certificate that is absent from the network configuration.

## Limitations

- The pending pool is memory-only by design. Pending transactions are lost on restart; they are re-sent by peers on reconnection only if those peers still hold them.
- Block construction does not yet consume the eligible-transaction selection; that wiring belongs to later mining controls.
- The confirmed-transaction set is rebuilt by scanning the canonical chain on each tip change. This is acceptable at the expected scale but is not optimized.
- Windows 11 behavior and the real three-laptop network test are not verified.
