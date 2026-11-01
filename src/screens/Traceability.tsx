import { useEffect, useState } from "react";
import { listBatches, listMaterials, viewBatchTraceability, viewMaterialTraceability, type BatchView, type MaterialView, type LineageEntry } from "../api/client";
import { buildViewProof } from "../blockchain/viewProof";
import { formatKg, shortKey } from "../utils/format";

interface Props {}

type ItemType = "batch" | "material";
interface ItemRow { id: string; type: ItemType; description: string; quantityKg: number; }

export default function Traceability({}: Props) {
  const [items, setItems] = useState<ItemRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [lineage, setLineage] = useState<LineageEntry[]>([]);
  const [lineageLoading, setLineageLoading] = useState(false);
  const [lineageError, setLineageError] = useState("");
  const [selectedItem, setSelectedItem] = useState<{ id: string; type: ItemType } | null>(null);

  useEffect(() => {
    setLoading(true);
    setError("");
    Promise.all([listBatches(), listMaterials()])
      .then(([b, m]) => {
        const batchRows: ItemRow[] = b.batches.map((batch: BatchView) => ({
          id: batch.batchId, type: "batch" as ItemType, description: batch.description, quantityKg: batch.quantityKg,
        }));
        const materialRows: ItemRow[] = m.materials.map((mat: MaterialView) => ({
          id: mat.materialId, type: "material" as ItemType, description: mat.description, quantityKg: mat.quantityKg,
        }));
        setItems([...batchRows, ...materialRows]);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Unable to load items."))
      .finally(() => setLoading(false));
  }, []);

  async function showTraceability(id: string, type: ItemType) {
    setLineageLoading(true);
    setLineageError("");
    setLineage([]);
    setSelectedItem({ id, type });
    try {
      if (type === "batch") {
        const proof = buildViewProof(id);
        const result = await viewBatchTraceability(id, proof);
        setLineage(result.lineage);
      } else {
        const proof = buildViewProof(id);
        const result = await viewMaterialTraceability(id, proof);
        setLineage(result.lineage);
      }
    } catch (e) {
      setLineageError(e instanceof Error ? e.message : "Unable to load traceability. You may not have access to this item's history.");
    } finally {
      setLineageLoading(false);
    }
  }

  return (
    <div className="screen">
      <h1>Traceability</h1>
      <p className="status">View the custody and processing history of a batch or recovered material. Access is limited to wallets involved in the item's history.</p>

      {error && <p className="status status-error">{error}</p>}
      {loading && <p className="status">Loading...</p>}

      {!loading && !error && (
        <div className="info-block">
          <h2>Select an item</h2>
          {items.length === 0 ? (
            <p className="empty-state">No batches or materials exist on this chain yet.</p>
          ) : (
            <table className="data-table">
              <thead>
                <tr><th>Type</th><th>ID</th><th>Description</th><th>Quantity</th><th></th></tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.type + item.id}>
                    <td>{item.type === "batch" ? "Batch" : "Material"}</td>
                    <td className="mono">{shortKey(item.id)}</td>
                    <td>{item.description}</td>
                    <td>{formatKg(item.quantityKg)}</td>
                    <td><button className="button button-small" onClick={() => showTraceability(item.id, item.type)}>View history</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {selectedItem && (
        <div className="panel detail-panel">
          <h2>Traceability for {selectedItem.type}: {shortKey(selectedItem.id)}</h2>
          {lineageLoading && <p className="status">Loading history...</p>}
          {lineageError && <p className="status status-error">{lineageError}</p>}
          {!lineageLoading && !lineageError && lineage.length === 0 && (
            <p className="empty-state">No traceability entries are available for this item.</p>
          )}
          {!lineageLoading && !lineageError && lineage.length > 0 && (
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
          )}
        </div>
      )}
    </div>
  );
}
