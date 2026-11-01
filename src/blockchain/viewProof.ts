import { canonicalBytes } from "../crypto/canonical";
import { sign, getUnlockedPublicKey } from "../wallet/walletSession";
import { sha256 } from "../crypto/hashing";

const VIEW_PROOF_TAG = "EWASTE-VIEW-PROOF-V1";

export interface ViewProof {
  walletPublicKey: string;
  itemId: string;
  issuedAt: string;
  signature: string;
}

function nowTimestamp(): string {
  const now = new Date();
  const utc = new Date(now.getTime() + now.getTimezoneOffset() * 60000);
  return utc.toISOString().replace(/\.\d{3}Z$/, "Z");
}

export function buildViewProof(itemId: string): ViewProof {
  const publicKey = getUnlockedPublicKey();
  if (publicKey === null) {
    throw new Error("The wallet is locked. Unlock it to view this item.");
  }
  const issuedAt = nowTimestamp();
  const body = {
    purpose: "view-history",
    walletPublicKey: publicKey,
    itemId,
    issuedAt,
  };
  const digest = sha256(
    new Uint8Array([
      ...new TextEncoder().encode(VIEW_PROOF_TAG),
      0,
      ...canonicalBytes(body),
    ]),
  );
  const signature = sign(digest);
  return { walletPublicKey: publicKey, itemId, issuedAt, signature };
}
