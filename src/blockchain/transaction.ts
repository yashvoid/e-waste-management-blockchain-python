import { canonicalBytes } from "../crypto/canonical";
import { domainHash, DOMAIN_TAGS } from "../crypto/hashing";
import { bytesToHex } from "../crypto/bytes";
import { sign, getUnlockedPublicKey } from "../wallet/walletSession";

export type PayloadValue = string | number | null | PayloadValue[] | { [key: string]: PayloadValue };
export type TransactionPayload = { [key: string]: PayloadValue };

export interface SignedTransaction {
  networkId: string;
  protocolVersion: number;
  timestamp: string;
  senderPublicKey: string;
  type: string;
  payload: TransactionPayload;
  nonce: number;
  txid: string;
  signature: string;
}

export interface ChainInfo {
  networkId: string;
  protocolVersion: number;
  tipHash: string;
  tipHeight: number;
  difficulty: number;
}

let cachedChainInfo: ChainInfo | null = null;

export async function fetchChainInfo(): Promise<ChainInfo> {
  const response = await fetch("/api/app/chain");
  if (!response.ok) throw new Error("Unable to read chain information from this node.");
  cachedChainInfo = (await response.json()) as ChainInfo;
  return cachedChainInfo;
}

export function getCachedChainInfo(): ChainInfo | null {
  return cachedChainInfo;
}

export function nowTimestamp(): string {
  const now = new Date();
  const utc = new Date(now.getTime() + now.getTimezoneOffset() * 60000);
  return utc.toISOString().replace(/\.\d{3}Z$/, "Z");
}

function transactionBody(
  networkId: string,
  protocolVersion: number,
  timestamp: string,
  senderPublicKey: string,
  txType: string,
  payload: TransactionPayload,
  nonce: number,
): Record<string, unknown> {
  return {
    networkId,
    protocolVersion,
    timestamp,
    senderPublicKey,
    type: txType,
    payload,
    nonce,
  };
}

function transactionDigest(body: Record<string, unknown>): Uint8Array {
  return domainHash(DOMAIN_TAGS.transaction, canonicalBytes(body));
}

export function buildAndSignTransaction(
  txType: string,
  payload: TransactionPayload,
  chainInfo: ChainInfo,
  nonce: number = 0,
): SignedTransaction {
  const publicKey = getUnlockedPublicKey();
  if (publicKey === null) {
    throw new Error("The wallet is locked. Unlock it to sign a transaction.");
  }
  const timestamp = nowTimestamp();
  const body = transactionBody(
    chainInfo.networkId,
    chainInfo.protocolVersion,
    timestamp,
    publicKey,
    txType,
    payload,
    nonce,
  );
  const digest = transactionDigest(body);
  const signature = sign(digest);
  const txid = bytesToHex(digest);
  return {
    ...body,
    txid,
    signature,
  } as SignedTransaction;
}
