import type { SignedTransaction, ChainInfo } from "../blockchain/transaction";
import type { ViewProof } from "../blockchain/viewProof";
import { clearOperatorToken, getOperatorToken } from "./operatorSession";

export type Role = "Generator" | "Collector" | "Transporter" | "Recycler" | "Material Processor";

export const ROLES: Role[] = [
  "Generator",
  "Collector",
  "Transporter",
  "Recycler",
  "Material Processor",
];

export interface CompletionStatus {
  completed: boolean;
  remainingGrams: number;
  remainingKg: number;
  processedGrams: number;
  processedKg: number;
  residualGrams: number;
  residualKg: number;
  discrepancyGrams: number;
  pendingGrams: number;
  pendingKg: number;
}

export interface BatchView {
  batchId: string;
  generator: string;
  description: string;
  quantityGrams: number;
  quantityKg: number;
  createdAt: string;
  completion: CompletionStatus | null;
  discrepancyGrams: number;
}

export interface TransferView {
  transferId: string;
  batchId: string;
  sender: string;
  receiver: string;
  declaredGrams: number;
  declaredKg: number;
  status: "pending" | "accepted" | "rejected" | "cancelled" | "expired";
  actualGrams: number | null;
  actualKg: number | null;
  reason: string;
  requestedAt: string;
  expiresAt: string;
}

export interface MaterialView {
  materialId: string;
  sourceOperation: string;
  parentItem: string;
  creator: string;
  description: string;
  quantityGrams: number;
  quantityKg: number;
  createdAt: string;
  completion: CompletionStatus | null;
}

export interface OperationView {
  operationId: string;
  processor: string;
  inputItem: string;
  inputGrams: number;
  inputKg: number;
  outputIds: string[];
  residualGrams: number;
  residualKg: number;
  method: string;
  processedAt: string;
}

export interface LineageEntry {
  kind: string;
  recordId: string;
  participants: string[];
  quantityGrams: number | null;
  quantityKg: number | null;
}

export interface TransactionStatus {
  txid: string;
  status: "confirmed" | "pending" | "unknown";
  blockHeight?: number;
  blockHash?: string;
}

export interface ParticipantView {
  walletPublicKey: string;
  role: Role;
  registeredAt: string;
  emailVersion: number;
  suspended: boolean;
}

export interface SubmissionResult {
  state: "accepted" | "known" | "confirmed" | "rejected" | "unavailable";
  detail: string;
  txid: string;
}

export interface PeerStatus {
  nodeId: string;
  state: string;
  detail: string;
  lastCheckedAt: string | null;
}

export interface NodeInfo {
  nodeId: string;
  listenHost: string;
  listenPort: number;
  peerPort: number;
  certificateSha256: string;
  networkId: string;
  protocolVersion: number;
  peers: { nodeId: string; host: string; port: number }[];
}

export interface StorageHealth {
  blockCount: number;
  tipHeight: number;
  tipHash: string;
  dataDir: string;
  locked: boolean;
}

export interface PendingCount {
  pendingCount: number;
}

export interface SyncOutcome {
  state: string;
  detail: string;
  blocksReceived: number;
  removedTransactions: number;
  newlyConfirmedTransactions: number;
}

export interface SyncStatus {
  lastSyncByPeer: Record<string, SyncOutcome>;
}

export interface MiningStatus {
  state: "stopped" | "running" | "error";
  blocksMined: number;
  lastBlockHash: string | null;
  lastBlockHeight: number | null;
  error: string | null;
}

export interface BackupExportResult {
  blocksExported: number;
}

export interface BackupImportResult {
  addedBlocks: number;
  canonicalChanged: boolean;
}

async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const response = await fetch(path, {
    ...init,
    headers: { Accept: "application/json", "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  return response;
}

async function getJson<T>(path: string): Promise<T> {
  const response = await apiFetch(path);
  if (!response.ok) {
    const detail = await extractError(response);
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await apiFetch(path, { method: "POST", body: JSON.stringify(body) });
  if (!response.ok) {
    const detail = await extractError(response);
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

async function extractError(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body === "object" && body !== null && "detail" in body) {
      return String((body as { detail: unknown }).detail);
    }
  } catch {
    // response body not JSON
  }
  return `Request failed (${response.status}).`;
}

export const SESSION_ENDED_MESSAGE = "Your operator session has ended. Sign in again to continue.";

export class OperatorSessionError extends Error {
  constructor() {
    super(SESSION_ENDED_MESSAGE);
    this.name = "OperatorSessionError";
  }
}

async function managementFetch(path: string, init?: RequestInit): Promise<Response> {
  const token = getOperatorToken();
  if (token === null) {
    throw new OperatorSessionError();
  }
  const response = await apiFetch(path, {
    ...init,
    headers: { Authorization: `Bearer ${token}`, ...(init?.headers ?? {}) },
  });
  if (response.status === 401) {
    clearOperatorToken();
    throw new OperatorSessionError();
  }
  return response;
}

async function getManagementJson<T>(path: string): Promise<T> {
  const response = await managementFetch(path);
  if (!response.ok) {
    throw new Error(await extractError(response));
  }
  return response.json() as Promise<T>;
}

async function postManagementJson<T>(path: string, body: unknown): Promise<T> {
  const response = await managementFetch(path, { method: "POST", body: JSON.stringify(body) });
  if (!response.ok) {
    throw new Error(await extractError(response));
  }
  return response.json() as Promise<T>;
}

export function signInOperator(password: string): Promise<{ token: string; idleTimeoutSeconds: number }> {
  return postJson("/api/node/session", { password });
}

export async function signOutOperator(): Promise<void> {
  const token = getOperatorToken();
  clearOperatorToken();
  if (token === null) {
    return;
  }
  await apiFetch("/api/node/session", {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  }).catch(() => undefined);
}

export function listBatches(): Promise<{ batches: BatchView[] }> {
  return getJson("/api/app/batches");
}

export function viewBatch(batchId: string, proof: ViewProof): Promise<BatchView> {
  return postJson(`/api/app/batches/${batchId}/view`, proof);
}

export function viewBatchTransfers(batchId: string, proof: ViewProof): Promise<{ batchId: string; transfers: TransferView[] }> {
  return postJson(`/api/app/batches/${batchId}/transfers/view`, proof);
}

export function viewBatchTraceability(batchId: string, proof: ViewProof): Promise<{ batchId: string; lineage: LineageEntry[] }> {
  return postJson(`/api/app/batches/${batchId}/traceability/view`, proof);
}

export function listMaterials(): Promise<{ materials: MaterialView[] }> {
  return getJson("/api/app/materials");
}

export function viewMaterial(materialId: string, proof: ViewProof): Promise<MaterialView> {
  return postJson(`/api/app/materials/${materialId}/view`, proof);
}

export function viewMaterialTraceability(materialId: string, proof: ViewProof): Promise<{ materialId: string; lineage: LineageEntry[] }> {
  return postJson(`/api/app/materials/${materialId}/traceability/view`, proof);
}

export function listOperations(): Promise<{ operations: OperationView[] }> {
  return getJson("/api/app/processing");
}

export function getOperation(operationId: string): Promise<OperationView> {
  return getJson(`/api/app/processing/${operationId}`);
}

export function getTransactionStatus(txid: string): Promise<TransactionStatus> {
  return getJson(`/api/app/transactions/${txid}`);
}

export function getChainStatus(): Promise<ChainInfo> {
  return getJson("/api/app/chain");
}

export function getPeerStatus(): Promise<{ peers: PeerStatus[] }> {
  return getJson("/api/app/peers");
}

export function getParticipant(walletPublicKey: string): Promise<ParticipantView> {
  return getJson(`/api/participants/${walletPublicKey}`);
}

export function requestRegistrationCode(email: string): Promise<{ status: string }> {
  return postJson("/api/participants/registration/codes", { email });
}

export function submitRegistrationAttestation(
  email: string,
  code: string,
  walletPublicKey: string,
  role: Role,
): Promise<{ attestation: unknown }> {
  return postJson("/api/participants/registration/attestations", { email, code, walletPublicKey, role });
}

export function submitTransaction(transaction: SignedTransaction): Promise<SubmissionResult> {
  return postJson("/api/app/transactions", { transaction });
}

export function submitTypedTransaction(
  txType: string,
  transaction: SignedTransaction,
): Promise<SubmissionResult> {
  return postJson(`/api/app/transactions/${txType}`, { transaction });
}

export function getNodeInfo(): Promise<NodeInfo> {
  return getManagementJson("/api/node/info");
}

export function getStorageHealth(): Promise<StorageHealth> {
  return getManagementJson("/api/node/storage");
}

export function getPendingCount(): Promise<PendingCount> {
  return getManagementJson("/api/node/pending");
}

export function getSyncStatus(): Promise<SyncStatus> {
  return getManagementJson("/api/node/sync");
}

export function getMiningStatus(): Promise<MiningStatus> {
  return getManagementJson("/api/node/mining");
}

export function startMining(): Promise<{ started: boolean; detail: string }> {
  return postManagementJson("/api/node/mining/start", {});
}

export function stopMining(): Promise<{ stopped: boolean; detail: string }> {
  return postManagementJson("/api/node/mining/stop", {});
}

export function exportBackup(path: string): Promise<BackupExportResult> {
  return postManagementJson("/api/node/backup/export", { path });
}

export function importBackup(path: string): Promise<BackupImportResult> {
  return postManagementJson("/api/node/backup/import", { path });
}
