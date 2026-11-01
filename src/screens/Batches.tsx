import { useEffect, useState, useCallback } from "react";
import { listBatches, submitTypedTransaction, type BatchView, type Role, type SubmissionResult } from "../api/client";
import { fetchChainInfo, buildAndSignTransaction } from "../blockchain/transaction";
import { formatKg, shortKey, kgInputToGrams } from "../utils/format";

interface Props {
  role: Role;
  onRefresh: () => void;
}

export default function Batches({ role, onRefresh }: Props) {
  const [batches, setBatches] = useState<BatchView[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [description, setDescription] = useState("");
  const [quantityKg, setQuantityKg] = useState("");
  const [submitError, setSubmitError] = useState("");
  const [submitBusy, setSubmitBusy] = useState(false);
  const [submitResult, setSubmitResult] = useState<SubmissionResult | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    listBatches()
      .then((r) => setBatches(r.batches))
      .catch((e) => setError(e instanceof Error ? e.message : "Unable to load batches."))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const canCreate = role === "Generator";

  async function handleCreate() {
    setSubmitError("");
    setSubmitResult(null);
    const grams = kgInputToGrams(quantityKg);
    if (!description.trim()) { setSubmitError("Enter a description for the e-waste batch."); return; }
    if (grams <= 0) { setSubmitError("Enter a quantity greater than zero kilograms."); return; }
    setSubmitBusy(true);
    try {
      const chainInfo = await fetchChainInfo();
      const tx = buildAndSignTransaction("batch.create", {
        description: description.trim(),
        quantityGrams: grams,
      }, chainInfo);
      const result = await submitTypedTransaction("batch.create", tx);
      setSubmitResult(result);
      setShowCreate(false);
      setDescription("");
      setQuantityKg("");
      onRefresh();
      load();
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : "Unable to create batch.");
    } finally {
      setSubmitBusy(false);
    }
  }

  return (
    <div className="screen">
      <h1>Batches</h1>
      {canCreate && !showCreate && (
        <button className="button" onClick={() => { setShowCreate(true); setSubmitError(""); setSubmitResult(null); }}>Create new batch</button>
      )}

      {showCreate && (
        <div className="panel form-panel">
          <h2>Create e-waste batch</h2>
          <label className="field-label">Description
            <input type="text" value={description} onChange={(e) => setDescription(e.target.value)} maxLength={500} />
          </label>
          <label className="field-label">Quantity (kilograms)
            <input type="text" value={quantityKg} onChange={(e) => setQuantityKg(e.target.value)} placeholder="e.g. 25.500" />
          </label>
          <p className="hint">Maximum three decimal places. The quantity is stored in whole grams.</p>
          {submitError && <p className="status status-error">{submitError}</p>}
          <div className="button-group">
            <button className="button" onClick={handleCreate} disabled={submitBusy}>{submitBusy ? "Submitting..." : "Create batch"}</button>
            <button className="button button-secondary" onClick={() => setShowCreate(false)} disabled={submitBusy}>Cancel</button>
          </div>
        </div>
      )}

      {submitResult && (
        <div className="panel result-panel">
          <p className="status status-ok">Batch creation submitted.</p>
          <p className="status">Status: {submitResult.state}. Transaction ID: {shortKey(submitResult.txid)}</p>
          <p className="hint">This means the transaction was accepted into the pending pool, not that it is confirmed on the chain. Check the Transfers or Traceability screen after a block is produced.</p>
        </div>
      )}

      {error && <p className="status status-error">{error}</p>}
      {loading && <p className="status">Loading...</p>}

      {!loading && !error && (
        <div className="info-block">
          <h2>Batches on this chain</h2>
          {batches.length === 0 ? (
            <p className="empty-state">No e-waste batches have been created on this chain yet.</p>
          ) : (
            <table className="data-table">
              <thead>
                <tr><th>Batch ID</th><th>Generator</th><th>Description</th><th>Quantity</th><th>Created</th><th>Remaining</th></tr>
              </thead>
              <tbody>
                {batches.map((b) => (
                  <tr key={b.batchId}>
                    <td className="mono">{shortKey(b.batchId)}</td>
                    <td className="mono">{shortKey(b.generator)}</td>
                    <td>{b.description}</td>
                    <td>{formatKg(b.quantityKg)}</td>
                    <td>{b.createdAt}</td>
                    <td>{b.completion ? formatKg(b.completion.remainingKg) : formatKg(b.quantityKg)}</td>
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
