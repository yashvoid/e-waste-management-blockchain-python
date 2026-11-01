import { gcm } from "@noble/ciphers/aes.js";
import { scryptAsync } from "@noble/hashes/scrypt.js";

export const SCRYPT_PARAMS = {
  N: 16384,
  r: 8,
  p: 1,
  dkLen: 32,
} as const;

export const SALT_LENGTH = 16;
export const NONCE_LENGTH = 12;
export const KEY_LENGTH = 32;
export const PRIVATE_KEY_LENGTH = 32;
export const GCM_TAG_LENGTH = 16;
export const CIPHERTEXT_LENGTH = PRIVATE_KEY_LENGTH + GCM_TAG_LENGTH;

const RANDOM_FILL_MAX = 65536;

export function randomBytes(length: number): Uint8Array {
  const buffer = new Uint8Array(length);
  let offset = 0;
  while (offset < length) {
    const chunk = Math.min(length - offset, RANDOM_FILL_MAX);
    crypto.getRandomValues(buffer.subarray(offset, offset + chunk));
    offset += chunk;
  }
  return buffer;
}

export function zeroBuffer(buffer: Uint8Array): void {
  buffer.fill(0);
}

export async function deriveEncryptionKey(
  passwordBytes: Uint8Array,
  salt: Uint8Array,
): Promise<Uint8Array> {
  if (salt.length !== SALT_LENGTH) {
    throw new Error("Invalid salt length.");
  }
  return scryptAsync(passwordBytes, salt, SCRYPT_PARAMS);
}

export function encryptPrivateKey(
  encryptionKey: Uint8Array,
  nonce: Uint8Array,
  privateKey: Uint8Array,
  aad: Uint8Array,
): Uint8Array {
  if (encryptionKey.length !== KEY_LENGTH) {
    throw new Error("Invalid encryption key length.");
  }
  if (nonce.length !== NONCE_LENGTH) {
    throw new Error("Invalid nonce length.");
  }
  if (privateKey.length !== PRIVATE_KEY_LENGTH) {
    throw new Error("Invalid private key length.");
  }
  const cipher = gcm(encryptionKey, nonce, aad);
  return cipher.encrypt(privateKey);
}

export function decryptPrivateKey(
  encryptionKey: Uint8Array,
  nonce: Uint8Array,
  ciphertext: Uint8Array,
  aad: Uint8Array,
): Uint8Array {
  if (encryptionKey.length !== KEY_LENGTH) {
    throw new Error("Invalid encryption key length.");
  }
  if (nonce.length !== NONCE_LENGTH) {
    throw new Error("Invalid nonce length.");
  }
  if (ciphertext.length !== CIPHERTEXT_LENGTH) {
    throw new Error("Invalid ciphertext length.");
  }
  const cipher = gcm(encryptionKey, nonce, aad);
  return cipher.decrypt(ciphertext);
}
