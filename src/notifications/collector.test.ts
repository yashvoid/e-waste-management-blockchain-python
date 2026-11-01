import { describe, expect, it } from "vitest";
import {
  collectTransferNotifications,
  collectOperationNotifications,
  collectBatchCompletionNotifications,
  collectMaterialCompletionNotifications,
  emptyPriorState,
} from "./collector";
import { notificationKey } from "./store";
import type { TransferView, OperationView, BatchView, MaterialView } from "../api/client";
import type { TransferSnapshot, OperationSnapshot } from "./types";

const MY_KEY = "0212345678901234567890123456789012345678901234567890123456789abcd";
const OTHER_KEY = "02abcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcd";

function makeTransfer(overrides: Partial<TransferView> = {}): TransferView {
  return {
    transferId: "t1",
    batchId: "b1",
    sender: MY_KEY,
    receiver: OTHER_KEY,
    declaredGrams: 10000,
    declaredKg: 10,
    status: "pending",
    actualGrams: null,
    actualKg: null,
    reason: "",
    requestedAt: "2026-11-01T10:00:00Z",
    expiresAt: "2026-11-03T10:00:00Z",
    ...overrides,
  };
}

function makeOperation(overrides: Partial<OperationView> = {}): OperationView {
  return {
    operationId: "op1",
    processor: MY_KEY,
    inputItem: "b1",
    inputGrams: 5000,
    inputKg: 5,
    outputIds: ["m1"],
    residualGrams: 500,
    residualKg: 0.5,
    method: "manual",
    processedAt: "2026-11-01T12:00:00Z",
    ...overrides,
  };
}

function makeBatch(overrides: Partial<BatchView> = {}): BatchView {
  return {
    batchId: "b1",
    generator: MY_KEY,
    description: "Test batch",
    quantityGrams: 10000,
    quantityKg: 10,
    createdAt: "2026-11-01T10:00:00Z",
    completion: null,
    discrepancyGrams: 0,
    ...overrides,
  };
}

function makeMaterial(overrides: Partial<MaterialView> = {}): MaterialView {
  return {
    materialId: "m1",
    sourceOperation: "op1",
    parentItem: "b1",
    creator: MY_KEY,
    description: "Recovered copper",
    quantityGrams: 3000,
    quantityKg: 3,
    createdAt: "2026-11-01T12:00:00Z",
    completion: null,
    ...overrides,
  };
}

describe("notificationKey", () => {
  it("produces deterministic keys from category and ids", () => {
    const k1 = notificationKey("incoming-transfer", { transferId: "t1", batchId: "b1" });
    const k2 = notificationKey("incoming-transfer", { transferId: "t1", batchId: "b1" });
    expect(k1).toBe(k2);
  });

  it("produces different keys for different categories", () => {
    const k1 = notificationKey("incoming-transfer", { transferId: "t1" });
    const k2 = notificationKey("transfer-accepted", { transferId: "t1" });
    expect(k1).not.toBe(k2);
  });

  it("produces different keys for different ids", () => {
    const k1 = notificationKey("incoming-transfer", { transferId: "t1" });
    const k2 = notificationKey("incoming-transfer", { transferId: "t2" });
    expect(k1).not.toBe(k2);
  });
});

describe("collectTransferNotifications", () => {
  it("detects a new incoming transfer request for the receiver", () => {
    const t = makeTransfer({ receiver: MY_KEY, sender: OTHER_KEY, status: "pending" });
    const prior = new Map<string, TransferSnapshot>();
    const result = collectTransferNotifications([t], prior, MY_KEY);
    expect(result.notifications).toHaveLength(1);
    expect(result.notifications[0].category).toBe("incoming-transfer");
    expect(result.notifications[0].transferId).toBe("t1");
  });

  it("does not create an incoming-transfer notification for the sender", () => {
    const t = makeTransfer({ sender: MY_KEY, receiver: OTHER_KEY, status: "pending" });
    const prior = new Map<string, TransferSnapshot>();
    const result = collectTransferNotifications([t], prior, MY_KEY);
    expect(result.notifications).toHaveLength(0);
  });

  it("does not create a notification for transfers not involving the participant", () => {
    const t = makeTransfer({ sender: OTHER_KEY, receiver: "02otherotherotherother" });
    const prior = new Map<string, TransferSnapshot>();
    const result = collectTransferNotifications([t], prior, MY_KEY);
    expect(result.notifications).toHaveLength(0);
  });

  it("detects transfer acceptance for the sender", () => {
    const t = makeTransfer({ sender: MY_KEY, status: "accepted", actualKg: 9.5 });
    const prior = new Map<string, TransferSnapshot>([
      ["t1", { ...t, status: "pending" } as TransferSnapshot],
    ]);
    const result = collectTransferNotifications([t], prior, MY_KEY);
    expect(result.notifications).toHaveLength(1);
    expect(result.notifications[0].category).toBe("transfer-accepted");
  });

  it("does not re-emit the same transfer on subsequent polls", () => {
    const t = makeTransfer({ receiver: MY_KEY, status: "pending" });
    const prior1 = new Map<string, TransferSnapshot>();
    const r1 = collectTransferNotifications([t], prior1, MY_KEY);
    const prior2 = r1.next;
    const r2 = collectTransferNotifications([t], prior2, MY_KEY);
    expect(r1.notifications).toHaveLength(1);
    expect(r2.notifications).toHaveLength(0);
  });

  it("detects rejection for the sender", () => {
    const t = makeTransfer({ sender: MY_KEY, status: "rejected" });
    const prior = new Map<string, TransferSnapshot>([
      ["t1", { ...t, status: "pending" } as TransferSnapshot],
    ]);
    const result = collectTransferNotifications([t], prior, MY_KEY);
    expect(result.notifications).toHaveLength(1);
    expect(result.notifications[0].category).toBe("transfer-rejected");
  });

  it("detects cancellation for the receiver", () => {
    const t = makeTransfer({ receiver: MY_KEY, status: "cancelled" });
    const prior = new Map<string, TransferSnapshot>([
      ["t1", { ...t, status: "pending" } as TransferSnapshot],
    ]);
    const result = collectTransferNotifications([t], prior, MY_KEY);
    expect(result.notifications).toHaveLength(1);
    expect(result.notifications[0].category).toBe("transfer-cancelled");
  });

  it("detects expiry for the sender", () => {
    const t = makeTransfer({ sender: MY_KEY, status: "expired" });
    const prior = new Map<string, TransferSnapshot>([
      ["t1", { ...t, status: "pending" } as TransferSnapshot],
    ]);
    const result = collectTransferNotifications([t], prior, MY_KEY);
    expect(result.notifications).toHaveLength(1);
    expect(result.notifications[0].category).toBe("transfer-expired");
  });

  it("detects expiry for the receiver", () => {
    const t = makeTransfer({ receiver: MY_KEY, status: "expired" });
    const prior = new Map<string, TransferSnapshot>([
      ["t1", { ...t, status: "pending" } as TransferSnapshot],
    ]);
    const result = collectTransferNotifications([t], prior, MY_KEY);
    expect(result.notifications).toHaveLength(1);
    expect(result.notifications[0].category).toBe("transfer-expired");
  });

  it("does not detect transfer-accepted when status changes from accepted to accepted", () => {
    const t = makeTransfer({ sender: MY_KEY, status: "accepted" });
    const prior = new Map<string, TransferSnapshot>([
      ["t1", { ...t, status: "accepted" } as TransferSnapshot],
    ]);
    const result = collectTransferNotifications([t], prior, MY_KEY);
    expect(result.notifications).toHaveLength(0);
  });

  it("produces no notifications for an empty transfer list", () => {
    const prior = new Map<string, TransferSnapshot>();
    const result = collectTransferNotifications([], prior, MY_KEY);
    expect(result.notifications).toHaveLength(0);
  });
});

describe("collectOperationNotifications", () => {
  it("detects a new processing operation by the participant", () => {
    const op = makeOperation({ processor: MY_KEY });
    const prior = new Map<string, OperationSnapshot>();
    const result = collectOperationNotifications([op], prior, MY_KEY);
    expect(result.notifications).toHaveLength(1);
    expect(result.notifications[0].category).toBe("processing-confirmed");
  });

  it("does not detect operations by other participants", () => {
    const op = makeOperation({ processor: OTHER_KEY });
    const prior = new Map<string, OperationSnapshot>();
    const result = collectOperationNotifications([op], prior, MY_KEY);
    expect(result.notifications).toHaveLength(0);
  });

  it("does not re-emit an operation on subsequent polls", () => {
    const op = makeOperation({ processor: MY_KEY });
    const prior1 = new Map<string, OperationSnapshot>();
    const r1 = collectOperationNotifications([op], prior1, MY_KEY);
    const r2 = collectOperationNotifications([op], r1.next, MY_KEY);
    expect(r1.notifications).toHaveLength(1);
    expect(r2.notifications).toHaveLength(0);
  });
});

describe("collectBatchCompletionNotifications", () => {
  it("detects when a batch transitions to completed", () => {
    const batch = makeBatch({
      completion: { completed: true, remainingGrams: 0, remainingKg: 0, processedGrams: 10000, processedKg: 10, residualGrams: 0, residualKg: 0, discrepancyGrams: 0, pendingGrams: 0, pendingKg: 0 },
    });
    const prior = new Map<string, { completed: boolean }>([["b1", { completed: false }]]);
    const result = collectBatchCompletionNotifications([batch], prior);
    expect(result.notifications).toHaveLength(1);
    expect(result.notifications[0].category).toBe("transaction-confirmed");
  });

  it("does not emit when the batch was already completed", () => {
    const batch = makeBatch({
      completion: { completed: true, remainingGrams: 0, remainingKg: 0, processedGrams: 10000, processedKg: 10, residualGrams: 0, residualKg: 0, discrepancyGrams: 0, pendingGrams: 0, pendingKg: 0 },
    });
    const prior = new Map<string, { completed: boolean }>([["b1", { completed: true }]]);
    const result = collectBatchCompletionNotifications([batch], prior);
    expect(result.notifications).toHaveLength(0);
  });

  it("does not emit when the batch is not yet completed", () => {
    const batch = makeBatch({ completion: null });
    const prior = new Map<string, { completed: boolean }>([["b1", { completed: false }]]);
    const result = collectBatchCompletionNotifications([batch], prior);
    expect(result.notifications).toHaveLength(0);
  });
});

describe("collectMaterialCompletionNotifications", () => {
  it("detects when a material transitions to completed", () => {
    const mat = makeMaterial({
      completion: { completed: true, remainingGrams: 0, remainingKg: 0, processedGrams: 3000, processedKg: 3, residualGrams: 0, residualKg: 0, discrepancyGrams: 0, pendingGrams: 0, pendingKg: 0 },
    });
    const prior = new Map<string, { completed: boolean }>([["m1", { completed: false }]]);
    const result = collectMaterialCompletionNotifications([mat], prior);
    expect(result.notifications).toHaveLength(1);
  });

  it("does not emit when the material was already completed", () => {
    const mat = makeMaterial({
      completion: { completed: true, remainingGrams: 0, remainingKg: 0, processedGrams: 3000, processedKg: 3, residualGrams: 0, residualKg: 0, discrepancyGrams: 0, pendingGrams: 0, pendingKg: 0 },
    });
    const prior = new Map<string, { completed: boolean }>([["m1", { completed: true }]]);
    const result = collectMaterialCompletionNotifications([mat], prior);
    expect(result.notifications).toHaveLength(0);
  });
});

describe("emptyPriorState", () => {
  it("returns empty maps", () => {
    const state = emptyPriorState();
    expect(state.transfers.size).toBe(0);
    expect(state.operations.size).toBe(0);
    expect(state.batches.size).toBe(0);
    expect(state.materials.size).toBe(0);
  });
});
