import type {
  BatchView,
  TransferView,
  OperationView,
  MaterialView,
} from "../api/client";
import type {
  NotificationItem,
  NotificationCategory,
  TransferSnapshot,
  OperationSnapshot,
} from "./types";
import { notificationKey } from "./store";
import { shortKey, formatKg } from "../utils/format";

/**
 * Notification collector.
 *
 * The collector compares the current backend-derived state against a previous
 * snapshot (kept in the hook's `useRef`).  When a transfer or operation appears
 * for the first time, or a transfer's status changes, a notification is
 * generated.  Each notification has a deterministic key so that subsequent polls
 * that return the same state do not produce duplicates.
 *
 * The collector never infers events that the backend does not surface.  It
 * does not report "transaction confirmed" for locally-submitted transactions;
 * that distinction is reserved for the transaction-status lookup, which is
 * authoritative.  The collector only reports transfer- and operation-level
 * events that are derived from confirmed chain state (transfers and operations
 * only exist once they are in a block).
 *
 * Pending incoming transfer requests are reported as they appear in the
 * transfer list — a pending transfer has already been accepted into a block
 * (the `transfer.request` transaction is confirmed), so "incoming transfer
 * request" is a confirmed event.
 */

export interface PriorState {
  transfers: Map<string, TransferSnapshot>;
  operations: Map<string, OperationSnapshot>;
  batches: Map<string, { completed: boolean }>;
  materials: Map<string, { completed: boolean }>;
}

export function emptyPriorState(): PriorState {
  return {
    transfers: new Map(),
    operations: new Map(),
    batches: new Map(),
    materials: new Map(),
  };
}

function transferSnapshot(t: TransferView): TransferSnapshot {
  return {
    transferId: t.transferId,
    batchId: t.batchId,
    status: t.status,
    sender: t.sender,
    receiver: t.receiver,
    declaredKg: t.declaredKg,
    actualKg: t.actualKg,
    reason: t.reason,
    requestedAt: t.requestedAt,
    expiresAt: t.expiresAt,
  };
}

function operationSnapshot(o: OperationView): OperationSnapshot {
  return {
    operationId: o.operationId,
    processor: o.processor,
    inputItem: o.inputItem,
    inputKg: o.inputKg,
    processedAt: o.processedAt,
  };
}

function createNotification(
  category: NotificationCategory,
  ids: Record<string, string | undefined>,
  title: string,
  detail: string,
  createdAt: string,
  extra: Partial<NotificationItem> = {},
): NotificationItem {
  const id = notificationKey(category, ids);
  return {
    id,
    category,
    title,
    detail,
    createdAt,
    read: false,
    ...extra,
  };
}

/**
 * Detect transfer-related notifications.
 * Returns new notifications and the updated transfer snapshot map.
 */
export function collectTransferNotifications(
  transfers: TransferView[],
  prior: Map<string, TransferSnapshot>,
  publicKey: string,
): { notifications: NotificationItem[]; next: Map<string, TransferSnapshot> } {
  const notifications: NotificationItem[] = [];
  const next = new Map<string, TransferSnapshot>();

  for (const t of transfers) {
    const snap = transferSnapshot(t);
    next.set(t.transferId, snap);

    const prev = prior.get(t.transferId);
    const isNew = prev === undefined;
    const statusChanged = prev !== undefined && prev.status !== t.status;

    if (!isNew && !statusChanged) continue;

    const involved =
      t.sender === publicKey || t.receiver === publicKey;
    if (!involved) continue;

    const baseIds = {
      transferId: t.transferId,
      batchId: t.batchId,
    };

    if (isNew && t.status === "pending") {
      if (t.receiver === publicKey) {
        notifications.push(
          createNotification(
            "incoming-transfer",
            baseIds,
            "Incoming transfer request",
            `Transfer ${shortKey(t.transferId)} from ${shortKey(t.sender)} — ${formatKg(t.declaredKg)}`,
            t.requestedAt,
            {
              transferId: t.transferId,
              itemId: t.batchId,
              targetScreen: "transfers",
              targetId: t.transferId,
            },
          ),
        );
      }
    }

    if (t.status === "accepted" && (isNew || (statusChanged && prev.status === "pending"))) {
      if (t.sender === publicKey) {
        notifications.push(
          createNotification(
            "transfer-accepted",
            baseIds,
            "Transfer accepted",
            `Transfer ${shortKey(t.transferId)} was accepted by ${shortKey(t.receiver)}` +
              (t.actualKg !== null ? ` — received ${formatKg(t.actualKg)}` : ""),
            t.requestedAt,
            {
              transferId: t.transferId,
              itemId: t.batchId,
              targetScreen: "transfers",
              targetId: t.transferId,
            },
          ),
        );
      }
    }

    if (t.status === "rejected" && (isNew || (statusChanged && prev.status === "pending"))) {
      if (t.sender === publicKey) {
        notifications.push(
          createNotification(
            "transfer-rejected",
            baseIds,
            "Transfer rejected",
            `Transfer ${shortKey(t.transferId)} was rejected by ${shortKey(t.receiver)}`,
            t.requestedAt,
            {
              transferId: t.transferId,
              itemId: t.batchId,
              targetScreen: "transfers",
              targetId: t.transferId,
            },
          ),
        );
      }
    }

    if (t.status === "cancelled" && (isNew || (statusChanged && prev.status === "pending"))) {
      if (t.receiver === publicKey) {
        notifications.push(
          createNotification(
            "transfer-cancelled",
            baseIds,
            "Transfer cancelled",
            `Transfer ${shortKey(t.transferId)} from ${shortKey(t.sender)} was cancelled`,
            t.requestedAt,
            {
              transferId: t.transferId,
              itemId: t.batchId,
              targetScreen: "transfers",
              targetId: t.transferId,
            },
          ),
        );
      }
    }

    if (t.status === "expired" && (isNew || (statusChanged && prev.status === "pending"))) {
      if (t.sender === publicKey || t.receiver === publicKey) {
        notifications.push(
          createNotification(
            "transfer-expired",
            baseIds,
            "Transfer expired",
            `Transfer ${shortKey(t.transferId)} expired`,
            t.expiresAt,
            {
              transferId: t.transferId,
              itemId: t.batchId,
              targetScreen: "transfers",
              targetId: t.transferId,
            },
          ),
        );
      }
    }
  }

  // Keep prior entries for transfers no longer returned (unlikely but safe).
  for (const [id, snap] of prior) {
    if (!next.has(id)) next.set(id, snap);
  }

  return { notifications, next };
}

/**
 * Detect processing-operation notifications for the participant who recorded
 * them.  Operations appear only when confirmed in a block.
 */
export function collectOperationNotifications(
  operations: OperationView[],
  prior: Map<string, OperationSnapshot>,
  publicKey: string,
): { notifications: NotificationItem[]; next: Map<string, OperationSnapshot> } {
  const notifications: NotificationItem[] = [];
  const next = new Map<string, OperationSnapshot>();

  for (const o of operations) {
    const snap = operationSnapshot(o);
    next.set(o.operationId, snap);

    if (o.processor !== publicKey) continue;

    const prev = prior.get(o.operationId);
    if (prev === undefined) {
      notifications.push(
        createNotification(
          "processing-confirmed",
          { operationId: o.operationId },
          "Processing confirmed",
          `Processing operation ${shortKey(o.operationId)} is confirmed on the chain — input ${formatKg(o.inputKg)}`,
          o.processedAt,
          {
            operationId: o.operationId,
            targetScreen: "processing",
            targetId: o.operationId,
          },
        ),
      );
    }
  }

  for (const [id, snap] of prior) {
    if (!next.has(id)) next.set(id, snap);
  }

  return { notifications, next };
}

/**
 * Detect batch completion state changes.
 */
export function collectBatchCompletionNotifications(
  batches: BatchView[],
  prior: Map<string, { completed: boolean }>,
): { notifications: NotificationItem[]; next: Map<string, { completed: boolean }> } {
  const notifications: NotificationItem[] = [];
  const next = new Map<string, { completed: boolean }>();

  for (const b of batches) {
    const completed = b.completion?.completed ?? false;
    next.set(b.batchId, { completed });

    const prev = prior.get(b.batchId);
    if (prev !== undefined && !prev.completed && completed) {
      notifications.push(
        createNotification(
          "transaction-confirmed",
          { batchId: b.batchId },
          "Batch completed",
          `Batch ${shortKey(b.batchId)} is fully processed`,
          b.createdAt,
          {
            itemId: b.batchId,
            targetScreen: "traceability",
            targetId: b.batchId,
          },
        ),
      );
    }
  }

  for (const [id, snap] of prior) {
    if (!next.has(id)) next.set(id, snap);
  }

  return { notifications, next };
}

/**
 * Detect material completion state changes.
 */
export function collectMaterialCompletionNotifications(
  materials: MaterialView[],
  prior: Map<string, { completed: boolean }>,
): { notifications: NotificationItem[]; next: Map<string, { completed: boolean }> } {
  const notifications: NotificationItem[] = [];
  const next = new Map<string, { completed: boolean }>();

  for (const m of materials) {
    const completed = m.completion?.completed ?? false;
    next.set(m.materialId, { completed });

    const prev = prior.get(m.materialId);
    if (prev !== undefined && !prev.completed && completed) {
      notifications.push(
        createNotification(
          "transaction-confirmed",
          { materialId: m.materialId },
          "Material fully processed",
          `Recovered material ${shortKey(m.materialId)} is fully processed`,
          m.createdAt,
          {
            itemId: m.materialId,
            targetScreen: "traceability",
            targetId: m.materialId,
          },
        ),
      );
    }
  }

  for (const [id, snap] of prior) {
    if (!next.has(id)) next.set(id, snap);
  }

  return { notifications, next };
}
