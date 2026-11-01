import { useEffect, useState } from "react";
import {
  getPeerStatus,
  getNodeInfo,
  getStorageHealth,
  getPendingCount,
  getSyncStatus,
  getMiningStatus,
  startMining,
  stopMining,
  exportBackup,
  importBackup,
  signOutOperator,
  OperatorSessionError,
  SESSION_ENDED_MESSAGE,
  type PeerStatus,
  type NodeInfo,
  type StorageHealth,
  type PendingCount,
  type SyncStatus,
  type MiningStatus,
  type BackupExportResult,
  type BackupImportResult,
} from "../api/client";
import { clearOperatorToken, getOperatorToken } from "../api/operatorSession";
import OperatorSignIn from "./OperatorSignIn";
import type { ChainInfo } from "../blockchain/transaction";
import type { ConnectionState } from "../api/nodeHealth";
import { shortKey } from "../utils/format";

interface Props {
  chainInfo: ChainInfo | null;
  connection: ConnectionState;
}

interface OperatorData {
  nodeInfo: NodeInfo | null;
  storage: StorageHealth | null;
  pending: PendingCount | null;
  sync: SyncStatus | null;
  mining: MiningStatus | null;
}

function settledValue<T>(result: PromiseSettledResult<T>): T | null {
  return result.status === "fulfilled" ? result.value : null;
}

function isSessionFailure(result: PromiseSettledResult<unknown>): boolean {
  return result.status === "rejected" && result.reason instanceof OperatorSessionError;
}

export default function NodeStatus({ chainInfo, connection }: Props) {
  const [signedIn, setSignedIn] = useState(() => getOperatorToken() !== null);
  const [sessionNotice, setSessionNotice] = useState("");
  const [operator, setOperator] = useState<OperatorData | null>(null);
  const [peers, setPeers] = useState<PeerStatus[]>([]);
  const [peersLoading, setPeersLoading] = useState(true);
  const [miningBusy, setMiningBusy] = useState(false);
  const [miningMessage, setMiningMessage] = useState("");
  const [backupPath, setBackupPath] = useState("");
  const [backupBusy, setBackupBusy] = useState(false);
  const [backupMessage, setBackupMessage] = useState("");

  const nodeInfo = operator?.nodeInfo ?? null;
  const storage = operator?.storage ?? null;
  const pending = operator?.pending ?? null;
  const sync = operator?.sync ?? null;
  const mining = operator?.mining ?? null;

  useEffect(() => {
    setPeersLoading(true);
    getPeerStatus()
      .then((r) => setPeers(r.peers))
      .catch(() => setPeers([]))
      .finally(() => setPeersLoading(false));
  }, [chainInfo]);

  useEffect(() => {
    if (!signedIn) return;
    Promise.allSettled([
      getNodeInfo(),
      getStorageHealth(),
      getPendingCount(),
      getSyncStatus(),
      getMiningStatus(),
    ]).then(([info, store, pend, syn, mine]) => {
      if ([info, store, pend, syn, mine].some(isSessionFailure)) {
        endSession(SESSION_ENDED_MESSAGE);
        return;
      }
      setOperator({
        nodeInfo: settledValue(info),
        storage: settledValue(store),
        pending: settledValue(pend),
        sync: settledValue(syn),
        mining: settledValue(mine),
      });
    });
  }, [signedIn, chainInfo]);

  function endSession(notice: string) {
    clearOperatorToken();
    setOperator(null);
    setSignedIn(false);
    setSessionNotice(notice);
  }

  function reportFailure(error: unknown, fallback: string, show: (message: string) => void) {
    if (error instanceof OperatorSessionError) {
      endSession(error.message);
      return;
    }
    show(error instanceof Error ? error.message : fallback);
  }

  async function handleSignOut() {
    await signOutOperator();
    setOperator(null);
    setSignedIn(false);
    setSessionNotice("You have signed out.");
  }

  function handleSignedIn() {
    setSessionNotice("");
    setSignedIn(true);
  }

  async function handleStartMining() {
    setMiningBusy(true);
    setMiningMessage("");
    try {
      const result = await startMining();
      setMiningMessage(result.detail);
      const status = await getMiningStatus();
      setOperator((prev) => (prev ? { ...prev, mining: status } : prev));
    } catch (e) {
      reportFailure(e, "Unable to start mining.", setMiningMessage);
    } finally {
      setMiningBusy(false);
    }
  }

  async function handleStopMining() {
    setMiningBusy(true);
    setMiningMessage("");
    try {
      const result = await stopMining();
      setMiningMessage(result.detail);
      const status = await getMiningStatus();
      setOperator((prev) => (prev ? { ...prev, mining: status } : prev));
    } catch (e) {
      reportFailure(e, "Unable to stop mining.", setMiningMessage);
    } finally {
      setMiningBusy(false);
    }
  }

  async function handleExport() {
    if (!backupPath.trim()) {
      setBackupMessage("Enter a file path for the backup.");
      return;
    }
    setBackupBusy(true);
    setBackupMessage("");
    try {
      const result: BackupExportResult = await exportBackup(backupPath.trim());
      setBackupMessage(`Exported ${result.blocksExported} block${result.blocksExported === 1 ? "" : "s"}.`);
    } catch (e) {
      reportFailure(e, "Backup export failed.", setBackupMessage);
    } finally {
      setBackupBusy(false);
    }
  }

  async function handleImport() {
    if (!backupPath.trim()) {
      setBackupMessage("Enter the path to a backup file.");
      return;
    }
    setBackupBusy(true);
    setBackupMessage("");
    try {
      const result: BackupImportResult = await importBackup(backupPath.trim());
      const parts: string[] = [];
      parts.push(`${result.addedBlocks} block${result.addedBlocks === 1 ? "" : "s"} added`);
      parts.push(result.canonicalChanged ? "chain tip updated" : "chain tip unchanged");
      setBackupMessage(parts.join(", ") + ".");
    } catch (e) {
      reportFailure(e, "Backup import failed.", setBackupMessage);
    } finally {
      setBackupBusy(false);
    }
  }

  const syncPeers = sync ? Object.entries(sync.lastSyncByPeer) : [];

  return (
    <div className="screen">
      <h1>Node status</h1>

      <div className="info-block">
        <h2>Connection</h2>
        <table className="data-table">
          <tbody>
            <tr><td>Node</td><td>{connection.kind === "connected" ? "Connected" : connection.kind === "checking" ? "Checking..." : "Unavailable"}</td></tr>
            {connection.kind === "unavailable" && (
              <tr><td>Reason</td><td>{connection.reason}</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {!signedIn && <OperatorSignIn notice={sessionNotice} onSignedIn={handleSignedIn} />}

      {signedIn && (
        <div className="info-block">
          <h2>Operator session</h2>
          <p className="hint">You are signed in to this node. The session ends after a period of inactivity.</p>
          <div className="button-group">
            <button className="button button-secondary button-small" onClick={handleSignOut}>
              Sign out
            </button>
          </div>
        </div>
      )}

      {signedIn && nodeInfo && (
        <div className="info-block">
          <h2>Node identity</h2>
          <table className="data-table">
            <tbody>
              <tr><td>Node ID</td><td className="mono">{nodeInfo.nodeId}</td></tr>
              <tr><td>Listen address</td><td>{nodeInfo.listenHost}:{nodeInfo.listenPort}</td></tr>
              <tr><td>Peer port</td><td>{nodeInfo.peerPort}</td></tr>
              <tr><td>Certificate SHA-256</td><td className="mono">{shortKey(nodeInfo.certificateSha256)}</td></tr>
              <tr><td>Network ID</td><td>{nodeInfo.networkId}</td></tr>
              <tr><td>Protocol version</td><td>{nodeInfo.protocolVersion}</td></tr>
              <tr><td>Configured peers</td><td>{nodeInfo.peers.length}</td></tr>
            </tbody>
          </table>
        </div>
      )}

      {chainInfo && (
        <div className="info-block">
          <h2>Chain</h2>
          <table className="data-table">
            <tbody>
              <tr><td>Block height</td><td>{chainInfo.tipHeight}</td></tr>
              <tr><td>Chain tip hash</td><td className="mono">{shortKey(chainInfo.tipHash)}</td></tr>
              <tr><td>Difficulty</td><td>{chainInfo.difficulty}</td></tr>
            </tbody>
          </table>
        </div>
      )}

      {signedIn && storage && (
        <div className="info-block">
          <h2>Storage</h2>
          <table className="data-table">
            <tbody>
              <tr><td>Total blocks</td><td>{storage.blockCount}</td></tr>
              <tr><td>Canonical height</td><td>{storage.tipHeight}</td></tr>
              <tr><td>Tip hash</td><td className="mono">{shortKey(storage.tipHash)}</td></tr>
              <tr><td>Data directory</td><td className="mono">{storage.dataDir}</td></tr>
              <tr><td>Lock state</td><td>{storage.locked ? "Locked" : "Available"}</td></tr>
            </tbody>
          </table>
        </div>
      )}

      {signedIn && pending && (
        <div className="info-block">
          <h2>Pending transactions</h2>
          <table className="data-table">
            <tbody>
              <tr><td>Pending count</td><td>{pending.pendingCount}</td></tr>
            </tbody>
          </table>
        </div>
      )}

      {signedIn && mining && (
        <div className="info-block">
          <h2>Mining</h2>
          <table className="data-table">
            <tbody>
              <tr><td>State</td><td>{mining.state}</td></tr>
              <tr><td>Blocks mined</td><td>{mining.blocksMined}</td></tr>
              {mining.lastBlockHash && (
                <tr><td>Last block hash</td><td className="mono">{shortKey(mining.lastBlockHash)}</td></tr>
              )}
              {mining.lastBlockHeight !== null && (
                <tr><td>Last block height</td><td>{mining.lastBlockHeight}</td></tr>
              )}
              {mining.error && (
                <tr><td>Error</td><td className="status-error">{mining.error}</td></tr>
              )}
            </tbody>
          </table>
          <div className="button-group">
            <button
              className="button button-small"
              onClick={handleStartMining}
              disabled={miningBusy || mining.state === "running"}
            >
              Start
            </button>
            <button
              className="button button-secondary button-small"
              onClick={handleStopMining}
              disabled={miningBusy || mining.state === "stopped"}
            >
              Stop
            </button>
          </div>
          {miningMessage && <p className="status">{miningMessage}</p>}
        </div>
      )}

      {signedIn && syncPeers.length > 0 && (
        <div className="info-block">
          <h2>Synchronization</h2>
          <table className="data-table">
            <thead>
              <tr><th>Peer</th><th>State</th><th>Detail</th><th>Blocks received</th><th>Transactions removed</th><th>Newly confirmed</th></tr>
            </thead>
            <tbody>
              {syncPeers.map(([peerId, outcome]) => (
                <tr key={peerId}>
                  <td className="mono">{shortKey(peerId)}</td>
                  <td>{outcome.state}</td>
                  <td>{outcome.detail}</td>
                  <td>{outcome.blocksReceived}</td>
                  <td>{outcome.removedTransactions}</td>
                  <td>{outcome.newlyConfirmedTransactions}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="info-block">
        <h2>Peers</h2>
        {peersLoading && <p className="status">Loading...</p>}
        {!peersLoading && (
          peers.length === 0 ? (
            <p className="empty-state">No peers are configured on this node.</p>
          ) : (
            <table className="data-table">
              <thead>
                <tr><th>Node ID</th><th>State</th><th>Detail</th><th>Last checked</th></tr>
              </thead>
              <tbody>
                {peers.map((p) => (
                  <tr key={p.nodeId}>
                    <td className="mono">{p.nodeId}</td>
                    <td>{p.state}</td>
                    <td>{p.detail}</td>
                    <td>{p.lastCheckedAt ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        )}
      </div>

      {signedIn && (
        <div className="info-block">
          <h2>Backup</h2>
          <p className="hint">Export the full chain to a file, or import blocks from a previous backup file.</p>
          <label className="field-label">
            File path
            <input
              type="text"
              value={backupPath}
              onChange={(e) => setBackupPath(e.target.value)}
              placeholder="C:\backups\chain-backup.jsonl"
            />
          </label>
          <div className="button-group">
            <button className="button button-small" onClick={handleExport} disabled={backupBusy}>
              Export
            </button>
            <button className="button button-secondary button-small" onClick={handleImport} disabled={backupBusy}>
              Import
            </button>
          </div>
          {backupMessage && <p className="status">{backupMessage}</p>}
        </div>
      )}
    </div>
  );
}
