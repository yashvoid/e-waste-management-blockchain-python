export type NotificationCategory =
  | "incoming-transfer"
  | "transfer-accepted"
  | "transfer-rejected"
  | "transfer-cancelled"
  | "transfer-expired"
  | "transaction-confirmed"
  | "transaction-pending"
  | "transaction-rejected"
  | "processing-confirmed";

export interface NotificationItem {
  id: string;
  category: NotificationCategory;
  title: string;
  detail: string;
  createdAt: string;
  read: boolean;
  itemId?: string;
  transferId?: string;
  operationId?: string;
  txid?: string;
  blockHeight?: number;
  targetScreen?: "transfers" | "batches" | "processing" | "materials" | "traceability" | "txstatus";
  targetId?: string;
}

export interface TransferSnapshot {
  transferId: string;
  batchId: string;
  status: "pending" | "accepted" | "rejected" | "cancelled" | "expired";
  sender: string;
  receiver: string;
  declaredKg: number;
  actualKg: number | null;
  reason: string;
  requestedAt: string;
  expiresAt: string;
}

export interface OperationSnapshot {
  operationId: string;
  processor: string;
  inputItem: string;
  inputKg: number;
  processedAt: string;
}
