import { sha256 as sha256Digest } from "@noble/hashes/sha2.js";

export const DOMAIN_TAGS = {
  transaction: "EWASTE-TX-V1",
  block: "EWASTE-BLOCK-V1",
  address: "EWASTE-ADDRESS-V1",
  transactionRoot: "EWASTE-BLOCK-TXROOT-V1",
} as const;

export type DomainTag = (typeof DOMAIN_TAGS)[keyof typeof DOMAIN_TAGS];

export function sha256(data: Uint8Array): Uint8Array {
  return sha256Digest(data);
}

export function domainHash(tag: DomainTag, payload: Uint8Array): Uint8Array {
  const tagBytes = new TextEncoder().encode(tag);
  const input = new Uint8Array(tagBytes.length + 1 + payload.length);
  input.set(tagBytes, 0);
  input.set(payload, tagBytes.length + 1);
  return sha256(input);
}
