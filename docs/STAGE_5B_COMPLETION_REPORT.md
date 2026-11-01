# Stage 5B Completion Report: Block Exchange and Chain Synchronization

Status: implementation completed. Focused automated verification passed in the Linux development environment. Full-suite rerun, Windows 11 verification and the three-laptop network test are outstanding.

## Files

- `backend/app/node/peer_protocol.py` (new): size limits (8 blocks per request, 64 locator hashes, response byte cap) and input patterns.
- `backend/app/node/peer_chain.py` (new): tip summary, known-block check, canonical locator, common-block search, canonical blocks after a hash. Reads take the storage lock.
- `backend/app/node/peer_server.py`: read-only endpoints `/peer/tip`, `/peer/locate`, `/peer/blocks`, with query validation.
- `backend/app/node/peer_client.py`: peer fetch functions with a streamed, byte-capped, strict JSON reader.
- `backend/app/node/chain_sync.py` (new): `ChainSynchronizer`, `SyncOutcome`. Storage calls run on a single-worker executor that is shut down at application exit.
- `backend/app/node/peer_monitor.py`: runs the synchronizer after each successful peer check.
- `backend/app/storage/chain_storage.py`: storage lock (`RLock`) and `add_blocks`.
- `backend/app/storage/block_records.py`: decoding of peer block objects.
- `backend/app/main.py`: connects the synchronizer to the monitor; shutdown order is monitor cancel, synchronizer close, listener stop, storage close.
- Tests: `backend/tests/test_block_exchange.py` (new); updated `test_peer_connectivity.py`, `test_node_startup.py`, `node_helpers.py`, `chain_helpers.py`.

## Peer endpoints

Read-only, behind the existing mutual TLS and peer compatibility checks.
- `/peer/tip`: the peer's hello (network, protocol, genesis) and its tip hash.
- `/peer/locate`: given a locator of up to 64 canonical hashes, returns the first hash the peer has on its canonical chain.
- `/peer/blocks`: returns up to 8 canonical blocks after a given hash.

## Bounded block exchange

Downloads proceed in batches of at most 8 blocks. Each response is read with a byte cap derived from the shared configuration's maximum block size. Locators are limited to 64 hashes. Peer-supplied JSON is parsed with the strict parser.

## Independent validation

A peer's tip, height and work are never trusted. Each batch is checked for linkage, then every block goes through the existing Stage 3 validation and `ChainStorage.add_block`. A block that fails validation rejects the batch; blocks before it in the batch are kept, as they were validated individually.

## Chain selection and reorganization

Competing branches are stored through the existing storage. The canonical chain is the one with the greatest cumulative work, with the lexicographic tip-hash tie-break from Stage 3. Removed and newly confirmed transactions are counted in the sync outcome.

## Shutdown and persistence safety

Shutdown originally waited only on the storage lock. That is not sufficient: a synchronizer thread that had been cancelled by the monitor could still be about to acquire the lock, or could write after storage closed. The synchronizer now routes all of its storage calls through a single-worker executor. At shutdown, the monitor is cancelled and awaited, then the executor is shut down with `wait=True`, which blocks until any running storage call finishes and cancels queued ones. Only after that does the listener stop and the storage close. Persistence remains append-only JSONL.

## Automated test results

Environment: a virtual environment at `backend/.venv`, created in the project folder. Its pip was bootstrapped from the official pip bootstrap script inside the venv only. Pinned packages came from `requirements.txt` and `requirements-dev.txt`. System Python was not modified.

Command (run from `backend/`):

    .venv/bin/python -m pytest -q -rfs tests/test_block_exchange.py tests/test_block_structures.py tests/test_block_validation.py tests/test_mining.py tests/test_chain_storage.py tests/test_chain_backup.py tests/test_startup_storage.py tests/test_strict_json.py tests/test_node_configuration.py tests/test_config.py tests/test_node_identity.py tests/test_node_startup.py tests/test_peer_connectivity.py tests/test_health.py

Result: 187 passed, 0 failed, 0 skipped.

Earlier run, before fixing test fixtures: 182 passed, 5 failed. All five were the incompatible-network tests (`test_block_exchange.py` 2 cases, `test_peer_connectivity.py` 3 cases). Cause: the test helper changed the network ID, protocol version or genesis hash without recomputing the genesis block, so node B's own configuration was inconsistent and failed at storage startup before any peer check. The fix changes the test helpers to derive a consistent genesis for each changed network. The genesis-hash case now uses a different genesis timestamp. Product code was not changed for this.

Not run in this session: the full backend suite (including crypto interoperability tests). The Stage 5A-era full run recorded 247 tests passed.

## Limitations and unverified items

- The full backend suite has not been rerun since the 5B changes.
- Windows 11 has not been tested.
- The real three-laptop test on university Wi-Fi has not been performed.
- Transaction propagation, the pending transaction pool, network status and registration are not implemented; they belong to later stages.
- Difficulty benchmarking on the target laptop is pending.
