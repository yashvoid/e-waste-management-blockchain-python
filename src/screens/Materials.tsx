import { useEffect, useState } from "react";
import { listMaterials, viewMaterial, viewMaterialTraceability, type MaterialView, type LineageEntry } from "../api/client";
import { buildViewProof } from "../blockchain/viewProof";
import { formatKg, shortKey } from "../utils/format";

export default function Materials() {
  const [materials, setMaterials] = useState<MaterialView[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<MaterialView | null>(null);
  const [lineage, setLineage] = useState<LineageEntry[]>([]);
  const [detailError, setDetailError] = useState("");
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    setError("");
    listMaterials()
      .then((r) => setMaterials(r.materials))
      .catch((e) => setError(e instanceof Error ? e.message : "Unable to load materials."))
      .finally(() => setLoading(false));
  }, []);

  async function showDetail(materialId: string) {
    setDetailLoading(true);
    setDetailError("");
    setSelected(null);
    setLineage([]);
    try {
      const proof = buildViewProof(materialId);
      const [mat, trace] = await Promise.all([
        viewMaterial(materialId, proof),
        viewMaterialTraceability(materialId, buildViewProof(materialId)),
      ]);
      setSelected(mat);
      setLineage(trace.lineage);
    } catch (e) {
      setDetailError(e instanceof Error ? e.message : "Unable to load material details. You may not have access to this material's history.");
    } finally {
      setDetailLoading(false);
    }
  }

  return (
    <div className="screen">
      <h1>Recovered materials</h1>
      {error && <p className="status status-error">{error}</p>}
      {loading && <p className="status">Loading...</p>}

      {!loading && !error && (
        <div className="info-block">
          <h2>Materials on this chain</h2>
          {materials.length === 0 ? (
            <p className="empty-state">No recovered materials have been produced on this chain yet.</p>
          ) : (
            <table className="data-table">
              <thead>
                <tr><th>Material ID</th><th>Creator</th><th>Description</th><th>Quantity</th><th>Created</th><th></th></tr>
              </thead>
              <tbody>
                {materials.map((m) => (
                  <tr key={m.materialId}>
                    <td className="mono">{shortKey(m.materialId)}</td>
                    <td className="mono">{shortKey(m.creator)}</td>
                    <td>{m.description}</td>
                    <td>{formatKg(m.quantityKg)}</td>
                    <td>{m.createdAt}</td>
                    <td><button className="button button-small" onClick={() => showDetail(m.materialId)}>View</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {detailLoading && <p className="status">Loading material details...</p>}
      {detailError && <p className="status status-error">{detailError}</p>}
      {selected && (
        <div className="panel detail-panel">
          <h2>Material details</h2>
          <table className="data-table">
            <tbody>
              <tr><td>Material ID</td><td className="mono">{selected.materialId}</td></tr>
              <tr><td>Description</td><td>{selected.description}</td></tr>
              <tr><td>Creator</td><td className="mono">{shortKey(selected.creator)}</td></tr>
              <tr><td>Source operation</td><td className="mono">{shortKey(selected.sourceOperation)}</td></tr>
              <tr><td>Parent item</td><td className="mono">{shortKey(selected.parentItem)}</td></tr>
              <tr><td>Quantity</td><td>{formatKg(selected.quantityKg)}</td></tr>
              <tr><td>Created</td><td>{selected.createdAt}</td></tr>
              {selected.completion && (
                <>
                  <tr><td>Remaining</td><td>{formatKg(selected.completion.remainingKg)}</td></tr>
                  <tr><td>Processed</td><td>{formatKg(selected.completion.processedKg)}</td></tr>
                  <tr><td>Residual</td><td>{formatKg(selected.completion.residualKg)}</td></tr>
                </>
              )}
            </tbody>
          </table>
          {lineage.length > 0 && (
            <div className="lineage-section">
              <h3>Traceability</h3>
              <table className="data-table">
                <thead>
                  <tr><th>Step</th><th>Type</th><th>Record ID</th><th>Participants</th><th>Quantity</th></tr>
                </thead>
                <tbody>
                  {lineage.map((entry, i) => (
                    <tr key={i}>
                      <td>{i + 1}</td>
                      <td>{entry.kind}</td>
                      <td className="mono">{shortKey(entry.recordId)}</td>
                      <td>{entry.participants.map((p) => shortKey(p)).join(", ")}</td>
                      <td>{entry.quantityKg !== null ? formatKg(entry.quantityKg) : "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {lineage.length === 0 && <p className="empty-state">No traceability entries are available for this material.</p>}
        </div>
      )}
    </div>
  );
}
