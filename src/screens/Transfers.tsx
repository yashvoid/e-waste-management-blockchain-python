import { useEffect, useState, useCallback } from "react";
import {
  listBatches,
  listMaterials,
  viewBatchTransfers,
  submitTypedTransaction,
  type BatchView,
  type MaterialView,
  type TransferView,
  type Role,
  type SubmissionResult,
} from "../api/client";
import { fetchChainInfo, buildAndSignTransaction } from "../blockchain/transaction";
import { buildViewProof } from "../blockchain/viewProof";
import { formatKg, shortKey, kgInputToGrams } from "../utils/format";

interface Props {
  role: Role;
  publicKey: string;
  onRefresh: () => void;
}

const NEXT_ROLE: Record<Role, Role | null> = {
  Generator: "Collector",
  Collector: "Transporter",
  Transporter: "Recycler",
  Recycler: "Material Processor",
  "Material Processor": null,
};

interface TransferableItem {
  id: string;
  description: string;
  quantityKg: number;
}

type ActionMode = "none" | "accept" | "reject";

export default function Transfers({ role, publicKey, onRefresh }: Props) {
  const [batches, setBatches] = useState<BatchView[]>([]);
  const [materials, setMaterials] = useState<MaterialView[]>([]);
  const [allTransfers, setAllTransfers] = useState<TransferView[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showRequest, setShowRequest] = useState(false);
  const [selectedItem, setSelectedItem] = useState("");
  const [receiverKey, setReceiverKey] = useState("");
  const [quantityKg, setQuantityKg] = useState("");
  const [submitError, setSubmitError] = useState("");
  const [submitBusy, setSubmitBusy] = useState(false);
  const [submitResult, setSubmitResult] = useState<SubmissionResult | null>(null);

  const [actionMode, setActionMode] = useState<ActionMode>("none");
  const [actionTransfer, setActionTransfer] = useState<TransferView | null>(null);
  const [actualKg, setActualKg] = useState("");
  const [discrepancyReason, setDiscrepancyReason] = useState("");
  const [rejectReason, setRejectReason] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [b, m] = await Promise.all([listBatches(), listMaterials()]);
      setBatches(b.batches);
      setMaterials(m.materials);

      const allItemIds = [...b.batches.map((x) => x.batchId), ...m.materials.map((x) => x.materialId)];
      const transferLists = await Promise.all(
        allItemIds.map((id) =>
          viewBatchTransfers(id, buildViewProof(id))
            .then((r) => r.transfers)
            .catch(() => [] as TransferView[]),
        ),
      );
      setAllTransfers(transferLists.flat());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to load data.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const nextRole = NEXT_ROLE[role];
  const canTransfer = nextRole !== null;

  const transferableItems: TransferableItem[] = role === "Recycler"
    ? materials.filter((m) => m.creator === publicKey).map((m) => ({ id: m.materialId, description: m.description, quantityKg: m.quantityKg }))
    : batches.map((b) => ({ id: b.batchId, description: b.description, quantityKg: b.quantityKg }));

  const incomingPending = allTransfers.filter(
    (t) => t.receiver === publicKey && t.status === "pending",
  );
  const outgoingPending = allTransfers.filter(
    (t) => t.sender === publicKey && t.status === "pending",
  );
  const completedTransfers = allTransfers.filter(
    (t) => (t.sender === publicKey || t.receiver === publicKey) && t.status !== "pending",
  );

  async function handleRequest() {
    setSubmitError("");
    setSubmitResult(null);
    const grams = kgInputToGrams(quantityKg);
    if (!selectedItem) { setSubmitError("Select a batch or material to transfer."); return; }
    if (!receiverKey.trim()) { setSubmitError("Enter the receiver's wallet public key."); return; }
    if (grams <= 0) { setSubmitError("Enter a quantity greater than zero kilograms."); return; }
    if (receiverKey.trim() === publicKey) { setSubmitError("You cannot transfer to your own wallet."); return; }
    setSubmitBusy(true);
    try {
      const chainInfo = await fetchChainInfo();
      const payload = {
        batchId: selectedItem,
        receiverPublicKey: receiverKey.trim(),
        quantityGrams: grams,
      };
      const tx = buildAndSignTransaction("transfer.request", payload, chainInfo);
      const result = await submitTypedTransaction("transfer.request", tx);
      setSubmitResult(result);
      setShowRequest(false);
      setSelectedItem(""); setReceiverKey(""); setQuantityKg("");
      onRefresh();
      load();
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : "Unable to submit transfer request.");
    } finally {
      setSubmitBusy(false);
    }
  }

  function startAccept(transfer: TransferView) {
    setActionTransfer(transfer);
    setActionMode("accept");
    setActualKg(transfer.declaredKg.toFixed(3));
    setDiscrepancyReason("");
    setSubmitError("");
  }

  function startReject(transfer: TransferView) {
    setActionTransfer(transfer);
    setActionMode("reject");
    setRejectReason("");
    setSubmitError("");
  }

  async function handleAccept() {
    if (!actionTransfer) return;
    setSubmitError("");
    setSubmitBusy(true);
    try {
      const actualGrams = kgInputToGrams(actualKg);
      if (actualGrams < 0) { setSubmitError("Enter a valid received quantity."); setSubmitBusy(false); return; }
      const declared = actionTransfer.declaredGrams;
      const hasDiscrepancy = actualGrams < declared;
      const reason = hasDiscrepancy ? discrepancyReason.trim() : "";
      if (hasDiscrepancy && !reason) {
        setSubmitError("A reason is required when the received quantity is less than the declared quantity.");
        setSubmitBusy(false);
        return;
      }
      const chainInfo = await fetchChainInfo();
      const payload = {
        transferId: actionTransfer.transferId,
        actualGrams,
        reason,
        senderApproval: "",
      };
      const tx = buildAndSignTransaction("transfer.accept", payload, chainInfo);
      const result = await submitTypedTransaction("transfer.accept", tx);
      setSubmitResult(result);
      setActionMode("none");
      setActionTransfer(null);
      setActualKg(""); setDiscrepancyReason("");
      onRefresh();
      load();
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : "Unable to accept transfer.");
    } finally {
      setSubmitBusy(false);
    }
  }

  async function handleReject() {
    if (!actionTransfer) return;
    setSubmitError("");
    if (!rejectReason.trim()) { setSubmitError("Enter a reason for rejecting this transfer."); setSubmitBusy(false); return; }
    setSubmitBusy(true);
    try {
      const chainInfo = await fetchChainInfo();
      const payload = {
        transferId: actionTransfer.transferId,
        reason: rejectReason.trim(),
      };
      const tx = buildAndSignTransaction("transfer.reject", payload, chainInfo);
      const result = await submitTypedTransaction("transfer.reject", tx);
      setSubmitResult(result);
      setActionMode("none");
      setActionTransfer(null);
      setRejectReason("");
      onRefresh();
      load();
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : "Unable to reject transfer.");
    } finally {
      setSubmitBusy(false);
    }
  }

  async function handleCancel(transfer: TransferView) {
    setSubmitError("");
    setSubmitBusy(true);
    try {
      const chainInfo = await fetchChainInfo();
      const payload = { transferId: transfer.transferId };
      const tx = buildAndSignTransaction("transfer.cancel", payload, chainInfo);
      const result = await submitTypedTransaction("transfer.cancel", tx);
      setSubmitResult(result);
      onRefresh();
      load();
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : "Unable to cancel transfer.");
    } finally {
      setSubmitBusy(false);
    }
  }

  return (
    <div className="screen">
      <h1>Transfers</h1>

      {submitResult && (
        <div className="panel result-panel">
          <p className="status status-ok">Transfer action submitted.</p>
          <p className="status">Status: {submitResult.state}. Transaction ID: {shortKey(submitResult.txid)}</p>
          <p className="hint">This transaction is in the pending pool. It will be confirmed when a block is produced.</p>
        </div>
      )}

      {submitError && <p className="status status-error">{submitError}</p>}

      {canTransfer && !showRequest && actionMode === "none" && (
        <button className="button" onClick={() => { setShowRequest(true); setSubmitError(""); setSubmitResult(null); }}>Request a transfer</button>
      )}

      {showRequest && (
        <div className="panel form-panel">
          <h2>Request custody transfer</h2>
          <p className="status">As a {role}, you can transfer to a {nextRole}.</p>
          <label className="field-label">Item to transfer
            <select value={selectedItem} onChange={(e) => setSelectedItem(e.target.value)}>
              <option value="">Select a batch or material</option>
              {transferableItems.map((item) => (
                <option key={item.id} value={item.id}>
                  {shortKey(item.id)} - {item.description} ({formatKg(item.quantityKg)})
                </option>
              ))}
            </select>
          </label>
          <label className="field-label">Receiver public key
            <input type="text" value={receiverKey} onChange={(e) => setReceiverKey(e.target.value)} placeholder="Compressed public key (66 hex characters)" />
          </label>
          <label className="field-label">Quantity (kilograms)
            <input type="text" value={quantityKg} onChange={(e) => setQuantityKg(e.target.value)} placeholder="e.g. 10.000" />
          </label>
          <div className="button-group">
            <button className="button" onClick={handleRequest} disabled={submitBusy}>{submitBusy ? "Submitting..." : "Submit transfer request"}</button>
            <button className="button button-secondary" onClick={() => setShowRequest(false)} disabled={submitBusy}>Cancel</button>
          </div>
        </div>
      )}

      {actionMode === "accept" && actionTransfer && (
        <div className="panel form-panel">
          <h2>Accept transfer {shortKey(actionTransfer.transferId)}</h2>
          <p className="status">Declared quantity: {formatKg(actionTransfer.declaredKg)} from {shortKey(actionTransfer.sender)}</p>
          <label className="field-label">Actual received quantity (kilograms)
            <input type="text" value={actualKg} onChange={(e) => setActualKg(e.target.value)} placeholder="e.g. 10.000" />
          </label>
          <p className="hint">If the received quantity is less than the declared quantity, a reason is required.</p>
          <label className="field-label">Discrepancy reason (required only if actual is less than declared)
            <input type="text" value={discrepancyReason} onChange={(e) => setDiscrepancyReason(e.target.value)} maxLength={500} />
          </label>
          <div className="button-group">
            <button className="button" onClick={handleAccept} disabled={submitBusy}>{submitBusy ? "Submitting..." : "Accept transfer"}</button>
            <button className="button button-secondary" onClick={() => { setActionMode("none"); setActionTransfer(null); }} disabled={submitBusy}>Cancel</button>
          </div>
        </div>
      )}

      {actionMode === "reject" && actionTransfer && (
        <div className="panel form-panel">
          <h2>Reject transfer {shortKey(actionTransfer.transferId)}</h2>
          <p className="status">From {shortKey(actionTransfer.sender)}, declared: {formatKg(actionTransfer.declaredKg)}</p>
          <label className="field-label">Reason for rejection
            <input type="text" value={rejectReason} onChange={(e) => setRejectReason(e.target.value)} maxLength={500} />
          </label>
          <div className="button-group">
            <button className="button" onClick={handleReject} disabled={submitBusy}>{submitBusy ? "Submitting..." : "Reject transfer"}</button>
            <button className="button button-secondary" onClick={() => { setActionMode("none"); setActionTransfer(null); }} disabled={submitBusy}>Cancel</button>
          </div>
        </div>
      )}

      {error && <p className="status status-error">{error}</p>}
      {loading && <p className="status">Loading...</p>}

      {!loading && !error && (
        <>
          {incomingPending.length > 0 && (
            <div className="info-block">
              <h2>Incoming transfer requests</h2>
              <table className="data-table">
                <thead>
                  <tr><th>Transfer</th><th>From</th><th>Item</th><th>Quantity</th><th>Expires</th><th></th></tr>
                </thead>
                <tbody>
                  {incomingPending.map((t) => (
                    <tr key={t.transferId}>
                      <td className="mono">{shortKey(t.transferId)}</td>
                      <td className="mono">{shortKey(t.sender)}</td>
                      <td className="mono">{shortKey(t.batchId)}</td>
                      <td>{formatKg(t.declaredKg)}</td>
                      <td>{t.expiresAt}</td>
                      <td>
                        <button className="button button-small" onClick={() => startAccept(t)} disabled={submitBusy}>Accept</button>
                        <button className="button button-secondary button-small" onClick={() => startReject(t)} disabled={submitBusy}>Reject</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {outgoingPending.length > 0 && (
            <div className="info-block">
              <h2>Your pending outgoing transfers</h2>
              <table className="data-table">
                <thead>
                  <tr><th>Transfer</th><th>To</th><th>Item</th><th>Quantity</th><th>Expires</th><th></th></tr>
                </thead>
                <tbody>
                  {outgoingPending.map((t) => (
                    <tr key={t.transferId}>
                      <td className="mono">{shortKey(t.transferId)}</td>
                      <td className="mono">{shortKey(t.receiver)}</td>
                      <td className="mono">{shortKey(t.batchId)}</td>
                      <td>{formatKg(t.declaredKg)}</td>
                      <td>{t.expiresAt}</td>
                      <td>
                        <button className="button button-secondary button-small" onClick={() => handleCancel(t)} disabled={submitBusy}>Cancel</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {canTransfer && !showRequest && (
            <div className="info-block">
              <h2>Items you can transfer</h2>
              {transferableItems.length === 0 ? (
                <p className="empty-state">No items available for transfer.</p>
              ) : (
                <table className="data-table">
                  <thead>
                    <tr><th>Item</th><th>Description</th><th>Quantity</th></tr>
                  </thead>
                  <tbody>
                    {transferableItems.map((item) => (
                      <tr key={item.id}>
                        <td className="mono">{shortKey(item.id)}</td>
                        <td>{item.description}</td>
                        <td>{formatKg(item.quantityKg)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {completedTransfers.length > 0 && (
            <div className="info-block">
              <h2>Transfer history</h2>
              <table className="data-table">
                <thead>
                  <tr><th>Transfer</th><th>Direction</th><th>Item</th><th>Quantity</th><th>Status</th><th>Actual</th><th>Reason</th></tr>
                </thead>
                <tbody>
                  {completedTransfers.map((t) => (
                    <tr key={t.transferId}>
                      <td className="mono">{shortKey(t.transferId)}</td>
                      <td>{t.sender === publicKey ? "Sent" : "Received"}</td>
                      <td className="mono">{shortKey(t.batchId)}</td>
                      <td>{formatKg(t.declaredKg)}</td>
                      <td>{t.status}</td>
                      <td>{t.actualKg !== null ? formatKg(t.actualKg) : "-"}</td>
                      <td>{t.reason || "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {!canTransfer && (
            <p className="status">Your role ({role}) cannot initiate custody transfers in this version. Material Processor outputs cannot be transferred further.</p>
          )}

          {incomingPending.length === 0 && outgoingPending.length === 0 && completedTransfers.length === 0 && canTransfer && !showRequest && (
            <p className="empty-state">No transfers to show. You can request a transfer using the button above.</p>
          )}

          {!canTransfer && incomingPending.length === 0 && outgoingPending.length === 0 && completedTransfers.length === 0 && (
            <p className="empty-state">No transfers to show.</p>
          )}
        </>
      )}
    </div>
  );
}
