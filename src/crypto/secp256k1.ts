import { secp256k1 } from "@noble/curves/secp256k1.js";
import { bytesToHex, hexToBytes } from "./bytes";
import { DOMAIN_TAGS, domainHash } from "./hashing";

const CURVE_ORDER = secp256k1.Point.Fn.ORDER;
const HALF_ORDER = CURVE_ORDER >> 1n;
const SIGNING_OPTIONS = { prehash: false, lowS: true, format: "compact" } as const;

export function parseCompressedPublicKey(publicKeyHex: string): Uint8Array {
  const bytes = hexToBytes(publicKeyHex, 33);
  if (bytes[0] !== 0x02 && bytes[0] !== 0x03) throw new Error("Public key must be compressed.");
  secp256k1.Point.fromBytes(bytes).assertValidity();
  return bytes;
}

export function parseCompactSignature(signatureHex: string): Uint8Array {
  const bytes = hexToBytes(signatureHex, 64);
  const r = BigInt(`0x${bytesToHex(bytes.subarray(0, 32))}`);
  const s = BigInt(`0x${bytesToHex(bytes.subarray(32))}`);
  if (r < 1n || r >= CURVE_ORDER) throw new Error("Signature r is out of range.");
  if (s < 1n || s > HALF_ORDER) throw new Error("Signature s must be low-S.");
  return bytes;
}

export function walletAddressFromPublicKey(publicKeyHex: string): string {
  const publicKey = parseCompressedPublicKey(publicKeyHex);
  return bytesToHex(domainHash(DOMAIN_TAGS.address, publicKey).slice(0, 20));
}

export function compressedPublicKeyFromPrivateKey(privateKeyHex: string): string {
  return bytesToHex(secp256k1.getPublicKey(hexToBytes(privateKeyHex, 32), true));
}

export function signDigest(digest: Uint8Array, privateKeyHex: string): string {
  if (digest.length !== 32) throw new Error("Digest must be 32 bytes.");
  return bytesToHex(secp256k1.sign(digest, hexToBytes(privateKeyHex, 32), SIGNING_OPTIONS));
}

export function verifyDigest(publicKeyHex: string, digest: Uint8Array, signatureHex: string): boolean {
  if (digest.length !== 32) return false;
  let publicKey: Uint8Array;
  let signature: Uint8Array;
  try {
    publicKey = parseCompressedPublicKey(publicKeyHex);
    signature = parseCompactSignature(signatureHex);
  } catch {
    return false;
  }
  return secp256k1.verify(signature, digest, publicKey, SIGNING_OPTIONS);
}
