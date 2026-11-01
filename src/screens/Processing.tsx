import { useEffect, useState, useCallback } from "react";
import { listBatches, listMaterials, listOperations, submitTypedTransaction, type BatchView, type MaterialView, type OperationView, type Role, type SubmissionResult } from "../api/client";
import { fetchChainInfo, buildAndSignTransaction } from "../blockchain/transaction";
import { formatKg, shortKey, kgInputToGrams } from "../utils/format";

interface Props {
  role: Role;
  publicKey: string;
  onRefresh: () => void;
}

interface OutputRow { description: string; quantityKg: string; }

export default function Processing({ role, publicKey, onRefresh }: Props) {
  const [batches, setBatches] = useState<BatchView[]>([]);
  const [materials, setMaterials] = useState<MaterialView[]>([]);
  const [operations, setOperations] = useState<OperationView[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [inputItem, setInputItem] = useState("");
  const [inputKg, setInputKg] = useState("");
  const [outputs, setOutputs] = useState<OutputRow[]>([{ description: "", quantityKg: "" }]);
  const [residualKg, setResidualKg] = useState("");
  const [method, setMethod] = useState("");
  const [submitError, setSubmitError] = useState("");
  const [submitBusy, setSubmitBusy] = useState(false);
  const [submitResult, setSubmitResult] = useState<SubmissionResult | null>(null);

  const canProcess = role === "Recycler" || role === "Material Processor";

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    Promise.all([listBatches(), listMaterials(), listOperations()])
      .then(([b, m, o]) => { setBatches(b.batches); setMaterials(m.materials); setOperations(o.operations); })
      .catch((e) => setError(e instanceof Error ? e.message : "Unable to load data."))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const processableItems: { id: string; description: string; quantityKg: number }[] = [
    ...(role === "Recycler" ? batches.map((b) => ({ id: b.batchId, description: b.description, quantityKg: b.quantityKg })) : []),
    ...(role === "Material Processor" ? materials.filter((m) => m.creator === publicKey).map((m) => ({ id: m.materialId, description: m.description, quantityKg: m.quantityKg })) : []),
  ];
  const myOperations = operations.filter((o) => o.processor === publicKey);

  async function handleProcess() {
    setSubmitError("");
    setSubmitResult(null);
    const inputGrams = kgInputToGrams(inputKg);
    const residualGrams = kgInputToGrams(residualKg);
    if (!inputItem) { setSubmitError("Select an input item to process."); return; }
    if (inputGrams <= 0) { setSubmitError("Enter an input quantity greater than zero."); return; }
    const validOutputs = outputs.filter((o) => o.description.trim() && o.quantityKg.trim());
    if (validOutputs.length === 0) { setSubmitError("Add at least one recovered material output."); return; }
    const outputGrams = validOutputs.map((o) => {
      const g = kgInputToGrams(o.quantityKg);
      if (g <= 0) { setSubmitError("Each output quantity must be greater than zero."); return -1; }
      return g;
    });
    if (outputGrams.some((g) => g < 0)) return;
    const totalOutput = outputGrams.reduce((a, b) => a + b, 0);
    if (totalOutput + residualGrams !== inputGrams) {
      setSubmitError(`Quantity does not balance. Input (${inputGrams} g) must equal outputs (${totalOutput} g) + residual (${residualGrams} g).`);
      return;
    }
    setSubmitBusy(true);
    try {
      const chainInfo = await fetchChainInfo();
      const tx = buildAndSignTransaction("processing.record", {
        inputItemId: inputItem,
        inputGrams: inputGrams,
        outputs: validOutputs.map((o, i) => ({
          description: o.description.trim(),
          quantityGrams: outputGrams[i],
        })),
        residualGrams: residualGrams,
        method: method.trim() || "unspecified",
      }, chainInfo);
      const result = await submitTypedTransaction("processing.record", tx);
      setSubmitResult(result);
      setShowForm(false);
      setInputItem(""); setInputKg(""); setOutputs([{ description: "", quantityKg: "" }]); setResidualKg(""); setMethod("");
      onRefresh();
      load();
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : "Unable to submit processing record.");
    } finally {
      setSubmitBusy(false);
    }
  }

  return (
    <div className="screen">
      <h1>Processing</h1>
      {!canProcess && <p className="status">Your role ({role}) cannot record processing operations.</p>}

      {canProcess && !showForm && (
        <button className="button" onClick={() => { setShowForm(true); setSubmitError(""); setSubmitResult(null); }}>Record processing operation</button>
      )}

      {showForm && (
        <div className="panel form-panel">
          <h2>Record processing operation</h2>
          <label className="field-label">Input item
            <select value={inputItem} onChange={(e) => setInputItem(e.target.value)}>
              <option value="">Select an item to process</option>
              {processableItems.map((item) => (
                <option key={item.id} value={item.id}>
                  {shortKey(item.id)} - {item.description} ({formatKg(item.quantityKg)})
                </option>
              ))}
            </select>
          </label>
          <label className="field-label">Input quantity (kilograms)
            <input type="text" value={inputKg} onChange={(e) => setInputKg(e.target.value)} placeholder="e.g. 50.000" />
          </label>
          <div className="outputs-section">
            <p className="field-label">Recovered material outputs</p>
            {outputs.map((out, i) => (
              <div key={i} className="output-row">
                <input type="text" placeholder="Description" value={out.description}
                  onChange={(e) => setOutputs((arr) => arr.map((o, j) => j === i ? { ...o, description: e.target.value } : o))} maxLength={500} />
                <input type="text" placeholder="Quantity (kg)" value={out.quantityKg}
                  onChange={(e) => setOutputs((arr) => arr.map((o, j) => j === i ? { ...o, quantityKg: e.target.value } : o))} />
                {outputs.length > 1 && (
                  <button className="button button-small" onClick={() => setOutputs((arr) => arr.filter((_, j) => j !== i))}>Remove</button>
                )}
              </div>
            ))}
            {outputs.length < 20 && (
              <button className="button button-secondary button-small" onClick={() => setOutputs((arr) => [...arr, { description: "", quantityKg: "" }])}>Add output</button>
            )}
          </div>
          <label className="field-label">Residual waste (kilograms)
            <input type="text" value={residualKg} onChange={(e) => setResidualKg(e.target.value)} placeholder="e.g. 2.000" />
          </label>
          <label className="field-label">Processing method (optional)
            <input type="text" value={method} onChange={(e) => setMethod(e.target.value)} maxLength={500} />
          </label>
          <p className="hint">Input quantity must equal the sum of all outputs plus the residual.</p>
          {submitError && <p className="status status-error">{submitError}</p>}
          <div className="button-group">
            <button className="button" onClick={handleProcess} disabled={submitBusy}>{submitBusy ? "Submitting..." : "Submit processing record"}</button>
            <button className="button button-secondary" onClick={() => setShowForm(false)} disabled={submitBusy}>Cancel</button>
          </div>
        </div>
      )}

      {submitResult && (
        <div className="panel result-panel">
          <p className="status status-ok">Processing record submitted.</p>
          <p className="status">Status: {submitResult.state}. Transaction ID: {shortKey(submitResult.txid)}</p>
        </div>
      )}

      {error && <p className="status status-error">{error}</p>}
      {loading && <p className="status">Loading...</p>}

      {!loading && !error && (
        <div className="info-block">
          <h2>Your processing operations</h2>
          {myOperations.length === 0 ? (
            <p className="empty-state">You have not recorded any processing operations.</p>
          ) : (
            <table className="data-table">
              <thead>
                <tr><th>Operation</th><th>Input item</th><th>Input</th><th>Outputs</th><th>Residual</th><th>Method</th></tr>
              </thead>
              <tbody>
                {myOperations.map((o) => (
                  <tr key={o.operationId}>
                    <td className="mono">{shortKey(o.operationId)}</td>
                    <td className="mono">{shortKey(o.inputItem)}</td>
                    <td>{formatKg(o.inputKg)}</td>
                    <td>{o.outputIds.map((id) => shortKey(id)).join(", ")}</td>
                    <td>{formatKg(o.residualKg)}</td>
                    <td>{o.method}</td>
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
