import { useEffect, useState } from "react";
import { listBatches, listMaterials, listOperations, getPeerStatus, viewBatchTransfers, type BatchView, type MaterialView, type OperationView, type PeerStatus, type TransferView, type Role } from "../api/client";
import { buildViewProof } from "../blockchain/viewProof";
import type { ChainInfo } from "../blockchain/transaction";
import { formatKg, shortKey } from "../utils/format";

interface Props {
  role: Role;
  publicKey: string;
  chainInfo: ChainInfo | null;
  refreshKey: number;
}

export default function Dashboard({ role, publicKey, chainInfo, refreshKey }: Props) {
  const [batches, setBatches] = useState<BatchView[]>([]);
  const [materials, setMaterials] = useState<MaterialView[]>([]);
  const [operations, setOperations] = useState<OperationView[]>([]);
  const [pendingIncoming, setPendingIncoming] = useState<TransferView[]>([]);
  const [peers, setPeers] = useState<PeerStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    (async () => {
      try {
        const [b, m, o, p] = await Promise.all([
          listBatches(),
          listMaterials(),
          listOperations(),
          getPeerStatus().catch(() => ({ peers: [] })),
        ]);
        if (!active) return;
        setBatches(b.batches);
        setMaterials(m.materials);
        setOperations(o.operations);
        setPeers(p.peers);

        const allItemIds = [...b.batches.map((x) => x.batchId), ...m.materials.map((x) => x.materialId)];
        const transferLists = await Promise.all(
          allItemIds.map((id) =>
            viewBatchTransfers(id, buildViewProof(id))
              .then((r) => r.transfers.filter((t) => t.receiver === publicKey && t.status === "pending"))
              .catch(() => [] as TransferView[]),
          ),
        );
        if (active) setPendingIncoming(transferLists.flat());
      } catch (e) {
        if (active) setError(e instanceof Error ? e.message : "Unable to load dashboard data.");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => { active = false; };
  }, [refreshKey]);

  const myBatches = batches.filter((b) => b.generator === publicKey);
  const myMaterials = materials.filter((m) => m.creator === publicKey);
  const myOperations = operations.filter((o) => o.processor === publicKey);

  return (
    <div className="screen">
      <h1>Dashboard</h1>
      <p className="status">Role: {role}</p>
      <p className="status">Wallet: {shortKey(publicKey)}</p>
      {chainInfo && (
        <div className="info-block">
          <h2>Chain status</h2>
          <table className="data-table">
            <tbody>
              <tr><td>Network</td><td>{chainInfo.networkId}</td></tr>
              <tr><td>Block height</td><td>{chainInfo.tipHeight}</td></tr>
              <tr><td>Protocol version</td><td>{chainInfo.protocolVersion}</td></tr>
            </tbody>
          </table>
        </div>
      )}

      {error && <p className="status status-error">{error}</p>}
      {loading && <p className="status">Loading...</p>}

      {!loading && !error && (
        <>
          {pendingIncoming.length > 0 && (
            <div className="info-block">
              <h2>Pending incoming transfer requests</h2>
              <table className="data-table">
                <thead>
                  <tr><th>Transfer</th><th>From</th><th>Item</th><th>Quantity</th><th>Expires</th></tr>
                </thead>
                <tbody>
                  {pendingIncoming.map((t) => (
                    <tr key={t.transferId}>
                      <td className="mono">{shortKey(t.transferId)}</td>
                      <td className="mono">{shortKey(t.sender)}</td>
                      <td className="mono">{shortKey(t.batchId)}</td>
                      <td>{formatKg(t.declaredKg)}</td>
                      <td>{t.expiresAt}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {role === "Generator" && (
            <div className="info-block">
              <h2>Batches you created</h2>
              {myBatches.length === 0 ? (
                <p className="empty-state">You have not created any e-waste batches.</p>
              ) : (
                <table className="data-table">
                  <thead>
                    <tr><th>Batch ID</th><th>Description</th><th>Quantity</th><th>Remaining</th><th>Created</th></tr>
                  </thead>
                  <tbody>
                    {myBatches.map((b) => (
                      <tr key={b.batchId}>
                        <td className="mono">{shortKey(b.batchId)}</td>
                        <td>{b.description}</td>
                        <td>{formatKg(b.quantityKg)}</td>
                        <td>{b.completion ? formatKg(b.completion.remainingKg) : formatKg(b.quantityKg)}</td>
                        <td>{b.createdAt}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {role !== "Generator" && (
            <div className="info-block">
              <h2>All batches on this chain</h2>
              {batches.length === 0 ? (
                <p className="empty-state">No e-waste batches have been created on this chain yet.</p>
              ) : (
                <table className="data-table">
                  <thead>
                    <tr><th>Batch ID</th><th>Generator</th><th>Description</th><th>Quantity</th><th>Remaining</th></tr>
                  </thead>
                  <tbody>
                    {batches.map((b) => (
                      <tr key={b.batchId}>
                        <td className="mono">{shortKey(b.batchId)}</td>
                        <td className="mono">{shortKey(b.generator)}</td>
                        <td>{b.description}</td>
                        <td>{formatKg(b.quantityKg)}</td>
                        <td>{b.completion ? formatKg(b.completion.remainingKg) : formatKg(b.quantityKg)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {(role === "Recycler" || role === "Material Processor") && (
            <>
              <div className="info-block">
                <h2>Processing operations you recorded</h2>
                {myOperations.length === 0 ? (
                  <p className="empty-state">You have not recorded any processing operations.</p>
                ) : (
                  <table className="data-table">
                    <thead>
                      <tr><th>Operation</th><th>Input item</th><th>Input</th><th>Residual</th><th>Method</th></tr>
                    </thead>
                    <tbody>
                      {myOperations.map((o) => (
                        <tr key={o.operationId}>
                          <td className="mono">{shortKey(o.operationId)}</td>
                          <td className="mono">{shortKey(o.inputItem)}</td>
                          <td>{formatKg(o.inputKg)}</td>
                          <td>{formatKg(o.residualKg)}</td>
                          <td>{o.method}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>

              <div className="info-block">
                <h2>Recovered materials you created</h2>
                {myMaterials.length === 0 ? (
                  <p className="empty-state">You have not produced any recovered materials.</p>
                ) : (
                  <table className="data-table">
                    <thead>
                      <tr><th>Material ID</th><th>Description</th><th>Quantity</th></tr>
                    </thead>
                    <tbody>
                      {myMaterials.map((m) => (
                        <tr key={m.materialId}>
                          <td className="mono">{shortKey(m.materialId)}</td>
                          <td>{m.description}</td>
                          <td>{formatKg(m.quantityKg)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </>
          )}

          <div className="info-block">
            <h2>Peer status</h2>
            {peers.length === 0 ? (
              <p className="empty-state">No peers are configured on this node.</p>
            ) : (
              <table className="data-table">
                <thead>
                  <tr><th>Node</th><th>State</th><th>Detail</th></tr>
                </thead>
                <tbody>
                  {peers.map((p) => (
                    <tr key={p.nodeId}>
                      <td className="mono">{p.nodeId}</td>
                      <td>{p.state}</td>
                      <td>{p.detail}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}
    </div>
  );
}
