import { hexToBytes, bytesToHex } from "../crypto/bytes";
import {
  SALT_LENGTH,
  NONCE_LENGTH,
  CIPHERTEXT_LENGTH,
} from "./encryption";
import { validateEnvelope, type WalletEnvelope } from "./walletEnvelope";

export const BACKUP_FORMAT_VERSION = 1;
export const BACKUP_MAGIC = "ewaste-wallet-backup";
export const BACKUP_FILE_EXTENSION = ".ewallet";
export const MAX_BACKUP_BYTES = 64 * 1024;

export interface BackupFile {
  format: string;
  backupVersion: number;
  envelope: SerializedEnvelope;
}

export interface SerializedEnvelope {
  version: number;
  kdf: string;
  scryptParams: { N: number; r: number; p: number };
  salt: string;
  cipher: string;
  nonce: string;
  ciphertext: string;
  publicKey: string;
  address: string;
  createdAt: string;
}

export function serializeEnvelope(envelope: WalletEnvelope): SerializedEnvelope {
  return {
    version: envelope.version,
    kdf: envelope.kdf,
    scryptParams: envelope.scryptParams,
    salt: bytesToHex(envelope.salt),
    cipher: envelope.cipher,
    nonce: bytesToHex(envelope.nonce),
    ciphertext: bytesToHex(envelope.ciphertext),
    publicKey: envelope.publicKey,
    address: envelope.address,
    createdAt: envelope.createdAt,
  };
}

export function deserializeEnvelope(data: SerializedEnvelope): WalletEnvelope {
  return {
    version: data.version,
    kdf: data.kdf,
    scryptParams: data.scryptParams,
    salt: hexToBytes(data.salt, SALT_LENGTH),
    cipher: data.cipher,
    nonce: hexToBytes(data.nonce, NONCE_LENGTH),
    ciphertext: hexToBytes(data.ciphertext, CIPHERTEXT_LENGTH),
    publicKey: data.publicKey,
    address: data.address,
    createdAt: data.createdAt,
  };
}

export function encodeBackup(envelope: WalletEnvelope): string {
  const backup: BackupFile = {
    format: BACKUP_MAGIC,
    backupVersion: BACKUP_FORMAT_VERSION,
    envelope: serializeEnvelope(envelope),
  };
  return JSON.stringify(backup);
}

export function parseBackup(raw: unknown): WalletEnvelope {
  if (typeof raw !== "object" || raw === null) {
    throw new Error("Invalid backup: not an object.");
  }
  const obj = raw as Record<string, unknown>;

  if (obj.format !== BACKUP_MAGIC) {
    throw new Error("Invalid backup: unrecognized format.");
  }
  if (obj.backupVersion !== BACKUP_FORMAT_VERSION) {
    throw new Error(`Unsupported backup version ${String(obj.backupVersion)}.`);
  }

  const env = obj.envelope;
  if (typeof env !== "object" || env === null) {
    throw new Error("Invalid backup: missing envelope.");
  }

  const serialized = env as Record<string, unknown>;
  const requiredFields: (keyof SerializedEnvelope)[] = [
    "version", "kdf", "scryptParams", "salt", "cipher",
    "nonce", "ciphertext", "publicKey", "address", "createdAt",
  ];
  for (const field of requiredFields) {
    if (!(field in serialized)) {
      throw new Error(`Invalid backup: missing field "${field}".`);
    }
  }

  const scrypt = serialized.scryptParams;
  if (typeof scrypt !== "object" || scrypt === null ||
      !("N" in scrypt) || !("r" in scrypt) || !("p" in scrypt)) {
    throw new Error("Invalid backup: malformed scrypt parameters.");
  }

  const stringFields: (keyof SerializedEnvelope)[] = [
    "salt", "nonce", "ciphertext", "publicKey", "address", "createdAt", "kdf", "cipher",
  ];
  for (const field of stringFields) {
    if (typeof serialized[field] !== "string") {
      throw new Error(`Invalid backup: field "${field}" must be a string.`);
    }
  }

  if (typeof serialized.version !== "number") {
    throw new Error("Invalid backup: version must be a number.");
  }

  const typed = serialized as unknown as SerializedEnvelope;
  let envelope: WalletEnvelope;
  try {
    envelope = deserializeEnvelope(typed);
  } catch {
    throw new Error("Invalid backup: corrupted binary fields.");
  }

  validateEnvelope(envelope);
  return envelope;
}
