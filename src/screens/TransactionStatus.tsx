import { useState, useEffect } from "react";
import { getTransactionStatus, type TransactionStatus as TxStatus } from "../api/client";
import { shortKey } from "../utils/format";

interface Props {
  focusTxid?: string | null;
}

export default function TransactionStatus({ focusTxid }: Props) {
  const [txid, setTxid] = useState("");
  const [result, setResult] = useState<TxStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function lookup(id: string) {
    const trimmed = id.trim();
    if (!trimmed) { setError("Enter a transaction ID."); return; }
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const status = await getTransactionStatus(trimmed);
      setResult(status);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to look up transaction.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (focusTxid) {
      setTxid(focusTxid);
      lookup(focusTxid);
    }
  }, [focusTxid]);

  return (
    <div className="screen">
      <h1>Transaction status</h1>
      <p className="status">Look up the status of a transaction by its ID.</p>
      <div className="form-panel">
        <label className="field-label">Transaction ID
          <input type="text" value={txid} onChange={(e) => setTxid(e.target.value)} placeholder="Transaction ID (hex)" />
        </label>
        <div className="button-group">
          <button className="button" onClick={() => lookup(txid)} disabled={loading}>{loading ? "Looking up..." : "Look up"}</button>
        </div>
        {error && <p className="status status-error">{error}</p>}
      </div>

      {result && (
        <div className="info-block">
          <h2>Result</h2>
          <table className="data-table">
            <tbody>
              <tr><td>Transaction ID</td><td className="mono">{shortKey(result.txid)}</td></tr>
              <tr><td>Status</td><td>{result.status}</td></tr>
              {result.blockHeight !== undefined && (
                <tr><td>Block height</td><td>{result.blockHeight}</td></tr>
              )}
              {result.blockHash !== undefined && (
                <tr><td>Block hash</td><td className="mono">{shortKey(result.blockHash)}</td></tr>
              )}
            </tbody>
          </table>
          {result.status === "pending" && (
            <p className="hint">This transaction is in the pending pool but has not yet been confirmed in a block.</p>
          )}
          {result.status === "confirmed" && (
            <p className="hint">This transaction is confirmed on the accepted chain.</p>
          )}
          {result.status === "unknown" && (
            <p className="hint">No transaction with this ID was found on this node.</p>
          )}
        </div>
      )}
    </div>
  );
}
