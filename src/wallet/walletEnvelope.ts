import { canonicalBytes } from "../crypto/canonical";
import {
  CIPHERTEXT_LENGTH,
  NONCE_LENGTH,
  SALT_LENGTH,
  SCRYPT_PARAMS,
  decryptPrivateKey,
  deriveEncryptionKey,
  encryptPrivateKey,
  randomBytes,
  zeroBuffer,
} from "./encryption";
import { derivePublicKeyAndAddress } from "./keyGeneration";

export interface WalletEnvelope {
  version: number;
  kdf: string;
  scryptParams: { N: number; r: number; p: number };
  salt: Uint8Array;
  cipher: string;
  nonce: Uint8Array;
  ciphertext: Uint8Array;
  publicKey: string;
  address: string;
  createdAt: string;
}

const COMPRESSED_KEY_PATTERN = /^0[23][0-9a-f]{64}$/;
const ADDRESS_PATTERN = /^[0-9a-f]{40}$/;

export class UnsupportedWalletFormatError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "UnsupportedWalletFormatError";
  }
}

export class WalletCorruptedError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "WalletCorruptedError";
  }
}

export class UnlockFailedError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "UnlockFailedError";
  }
}

export function buildAad(envelope: {
  version: number;
  kdf: string;
  scryptParams: { N: number; r: number; p: number };
  cipher: string;
  publicKey: string;
  address: string;
  createdAt: string;
}): Uint8Array {
  return canonicalBytes({
    version: envelope.version,
    kdf: envelope.kdf,
    scryptParams: envelope.scryptParams,
    cipher: envelope.cipher,
    publicKey: envelope.publicKey,
    address: envelope.address,
    createdAt: envelope.createdAt,
  });
}

function validateScryptParams(params: unknown): asserts params is { N: number; r: number; p: number } {
  if (
    typeof params !== "object" || params === null ||
    !("N" in params) || !("r" in params) || !("p" in params) ||
    params.N !== SCRYPT_PARAMS.N || params.r !== SCRYPT_PARAMS.r || params.p !== SCRYPT_PARAMS.p
  ) {
    throw new UnsupportedWalletFormatError("Unsupported scrypt parameters.");
  }
}

export function validateEnvelope(obj: unknown): asserts obj is WalletEnvelope {
  if (typeof obj !== "object" || obj === null) {
    throw new UnsupportedWalletFormatError("Wallet envelope must be an object.");
  }
  const e = obj as Record<string, unknown>;

  if (e.version !== 1) {
    throw new UnsupportedWalletFormatError("Unsupported wallet version.");
  }
  if (e.kdf !== "scrypt") {
    throw new UnsupportedWalletFormatError("Unsupported KDF algorithm.");
  }
  if (e.cipher !== "aes-256-gcm") {
    throw new UnsupportedWalletFormatError("Unsupported cipher algorithm.");
  }

  validateScryptParams(e.scryptParams);

  if (!(e.salt instanceof Uint8Array) || e.salt.length !== SALT_LENGTH) {
    throw new UnsupportedWalletFormatError("Invalid salt.");
  }
  if (!(e.nonce instanceof Uint8Array) || e.nonce.length !== NONCE_LENGTH) {
    throw new UnsupportedWalletFormatError("Invalid nonce.");
  }
  if (!(e.ciphertext instanceof Uint8Array) || e.ciphertext.length !== CIPHERTEXT_LENGTH) {
    throw new UnsupportedWalletFormatError("Invalid ciphertext.");
  }
  if (typeof e.publicKey !== "string" || !COMPRESSED_KEY_PATTERN.test(e.publicKey)) {
    throw new UnsupportedWalletFormatError("Invalid public key.");
  }
  if (typeof e.address !== "string" || !ADDRESS_PATTERN.test(e.address)) {
    throw new UnsupportedWalletFormatError("Invalid address.");
  }
  if (typeof e.createdAt !== "string" || !isValidIso8601(e.createdAt)) {
    throw new UnsupportedWalletFormatError("Invalid creation timestamp.");
  }
}

function isValidIso8601(value: string): boolean {
  if (typeof value !== "string") return false;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return false;
  return value.includes("T") && (value.endsWith("Z") || value.includes("+") || value.includes("-"));
}

export async function createEnvelope(
  privateKey: Uint8Array,
  publicKeyHex: string,
  address: string,
  passwordBytes: Uint8Array,
): Promise<WalletEnvelope> {
  const salt = randomBytes(SALT_LENGTH);
  const nonce = randomBytes(NONCE_LENGTH);
  const createdAt = new Date().toISOString();
  const partialEnvelope = {
    version: 1,
    kdf: "scrypt",
    scryptParams: { N: SCRYPT_PARAMS.N, r: SCRYPT_PARAMS.r, p: SCRYPT_PARAMS.p },
    cipher: "aes-256-gcm",
    publicKey: publicKeyHex,
    address,
    createdAt,
  };
  const aad = buildAad(partialEnvelope);

  let encryptionKey: Uint8Array | null = null;
  try {
    encryptionKey = await deriveEncryptionKey(passwordBytes, salt);
    const ciphertext = encryptPrivateKey(encryptionKey, nonce, privateKey, aad);
    return {
      ...partialEnvelope,
      salt,
      nonce,
      ciphertext,
    };
  } finally {
    if (encryptionKey !== null) zeroBuffer(encryptionKey);
  }
}

export async function openEnvelope(
  envelope: WalletEnvelope,
  passwordBytes: Uint8Array,
): Promise<Uint8Array> {
  validateEnvelope(envelope);
  const aad = buildAad(envelope);

  let encryptionKey: Uint8Array | null = null;
  let privateKey: Uint8Array | null = null;
  try {
    encryptionKey = await deriveEncryptionKey(passwordBytes, envelope.salt);
    try {
      privateKey = decryptPrivateKey(encryptionKey, envelope.nonce, envelope.ciphertext, aad);
    } catch {
      throw new UnlockFailedError("Unable to unlock the wallet. Check your password or the wallet may be corrupted.");
    }
    const { publicKeyHex, address } = derivePublicKeyAndAddress(privateKey);
    if (publicKeyHex !== envelope.publicKey || address !== envelope.address) {
      zeroBuffer(privateKey);
      privateKey = null;
      throw new WalletCorruptedError("Wallet metadata does not match the decrypted private key.");
    }
    const result = privateKey;
    privateKey = null;
    return result;
  } finally {
    if (encryptionKey !== null) zeroBuffer(encryptionKey);
    if (privateKey !== null) zeroBuffer(privateKey);
  }
}
