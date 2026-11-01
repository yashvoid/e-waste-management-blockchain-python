import { bytesToHex } from "../crypto/bytes";
import { signDigest } from "../crypto/secp256k1";
import { createEnvelope, openEnvelope, validateEnvelope, type WalletEnvelope } from "./walletEnvelope";
import { loadWallet, saveWallet, listWalletAddresses } from "./walletStore";
import { zeroBuffer } from "./encryption";
import { generateWalletKeyPair } from "./keyGeneration";
import {
  BACKUP_FILE_EXTENSION,
  encodeBackup,
  parseBackup,
  MAX_BACKUP_BYTES,
} from "./backupFormat";

const INACTIVITY_TIMEOUT_MS = 15 * 60 * 1000;
const DIGEST_LENGTH = 32;

const LONE_SURROGATE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/;
const MIN_PASSWORD_CODE_POINTS = 12;
const MAX_PASSWORD_UTF8_BYTES = 1024;

const hasDocument = typeof document !== "undefined";
const hasWindow = typeof window !== "undefined";

export class WalletLockedError extends Error {
  constructor() {
    super("The wallet is locked. Unlock it to continue.");
    this.name = "WalletLockedError";
  }
}

export class WalletStateError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "WalletStateError";
  }
}

function validatePassword(password: string): void {
  if (LONE_SURROGATE.test(password)) {
    throw new Error("Password contains invalid characters.");
  }
  if ([...password].length < MIN_PASSWORD_CODE_POINTS) {
    throw new Error("Password must be at least 12 characters.");
  }
  const utf8Length = new TextEncoder().encode(password).length;
  if (utf8Length > MAX_PASSWORD_UTF8_BYTES) {
    throw new Error("Password is too long.");
  }
}

function encodePassword(password: string): Uint8Array {
  return new TextEncoder().encode(password);
}

interface UnlockedState {
  privateKey: Uint8Array;
  publicKey: string;
  address: string;
  lastActivity: number;
  timerId: ReturnType<typeof setTimeout>;
}

let unlocked: UnlockedState | null = null;
let visibilityListener: ((event: Event) => void) | null = null;
let unloadListener: ((event: Event) => void) | null = null;

function now(): number {
  return performance.now();
}

function clearTimer(state: UnlockedState): void {
  clearTimeout(state.timerId);
}

function clearUnlockedState(): void {
  if (unlocked === null) return;
  clearTimer(unlocked);
  zeroBuffer(unlocked.privateKey);
  unlocked = null;
}

function scheduleAutoLock(state: UnlockedState): void {
  clearTimeout(state.timerId);
  state.timerId = setTimeout(() => {
    lock();
  }, INACTIVITY_TIMEOUT_MS);
}

function ensureVisibilityListener(): void {
  if (visibilityListener !== null || !hasDocument) return;
  visibilityListener = () => {
    if (document.hidden) lock();
  };
  document.addEventListener("visibilitychange", visibilityListener);
}

function ensureUnloadListener(): void {
  if (unloadListener !== null || !hasWindow) return;
  unloadListener = () => {
    lock();
  };
  window.addEventListener("beforeunload", unloadListener);
}

function removeListeners(): void {
  if (visibilityListener !== null) {
    if (hasDocument) {
      document.removeEventListener("visibilitychange", visibilityListener);
    }
    visibilityListener = null;
  }
  if (unloadListener !== null) {
    if (hasWindow) {
      window.removeEventListener("beforeunload", unloadListener);
    }
    unloadListener = null;
  }
}

export function isUnlocked(): boolean {
  return unlocked !== null;
}

export function getUnlockedAddress(): string | null {
  return unlocked?.address ?? null;
}

export function getUnlockedPublicKey(): string | null {
  return unlocked?.publicKey ?? null;
}

export function lock(): void {
  clearUnlockedState();
}

export async function unlock(address: string, password: string): Promise<void> {
  if (unlocked !== null) {
    throw new WalletStateError("A wallet is already unlocked.");
  }
  validatePassword(password);
  const passwordBytes = encodePassword(password);

  let envelope: WalletEnvelope | undefined;
  try {
    envelope = await loadWallet(address);
  } catch {
    throw new Error("Unable to access wallet storage.");
  }

  if (envelope === undefined) {
    zeroBuffer(passwordBytes);
    throw new Error("No wallet found for this address.");
  }

  let privateKey: Uint8Array;
  try {
    privateKey = await openEnvelope(envelope, passwordBytes);
  } finally {
    zeroBuffer(passwordBytes);
  }

  const state: UnlockedState = {
    privateKey,
    publicKey: envelope.publicKey,
    address,
    lastActivity: now(),
    timerId: 0 as unknown as ReturnType<typeof setTimeout>,
  };
  unlocked = state;
  scheduleAutoLock(state);
  ensureVisibilityListener();
  ensureUnloadListener();
}

export function sign(digest: Uint8Array): string {
  if (unlocked === null) {
    throw new WalletLockedError();
  }
  if (!(digest instanceof Uint8Array) || digest.length !== DIGEST_LENGTH) {
    throw new Error("Digest must be a 32-byte Uint8Array.");
  }

  if (now() - unlocked.lastActivity >= INACTIVITY_TIMEOUT_MS) {
    clearUnlockedState();
    removeListeners();
    throw new WalletLockedError();
  }

  const privateKeyHex = bytesToHex(unlocked.privateKey);
  const signature = signDigest(digest, privateKeyHex);

  unlocked.lastActivity = now();
  scheduleAutoLock(unlocked);
  return signature;
}

export async function createWallet(password: string): Promise<string> {
  validatePassword(password);
  if (unlocked !== null) {
    throw new WalletStateError("Lock the current wallet before creating a new one.");
  }

  let passwordBytes = encodePassword(password);
  let privateKey: Uint8Array | null = null;

  try {
    const generated = generateWalletKeyPair();
    privateKey = generated.privateKey;

    const envelope = await createEnvelope(
      privateKey,
      generated.publicKeyHex,
      generated.address,
      passwordBytes,
    );
    await saveWallet(envelope);
    return generated.address;
  } finally {
    zeroBuffer(passwordBytes);
    if (privateKey !== null) zeroBuffer(privateKey);
  }
}

export function _resetSession(): void {
  clearUnlockedState();
  removeListeners();
}

export async function exportWalletBackup(address: string): Promise<{ content: string; filename: string }> {
  const envelope = await loadWallet(address);
  if (envelope === undefined) {
    throw new Error("No wallet found for this address.");
  }
  validateEnvelope(envelope);
  const content = encodeBackup(envelope);
  if (content.length > MAX_BACKUP_BYTES) {
    throw new Error("Backup exceeds the maximum allowed size.");
  }
  const shortAddr = address.slice(0, 8);
  const filename = `wallet-${shortAddr}${BACKUP_FILE_EXTENSION}`;
  return { content, filename };
}

export async function importWalletBackup(
  rawJson: string,
  password: string,
): Promise<string> {
  if (rawJson.length > MAX_BACKUP_BYTES) {
    throw new Error("Backup file exceeds the maximum allowed size.");
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(rawJson);
  } catch {
    throw new Error("Invalid backup: not valid JSON.");
  }

  const envelope = parseBackup(parsed);
  validateEnvelope(envelope);

  const existingAddresses = await listWalletAddresses();
  if (existingAddresses.includes(envelope.address)) {
    throw new Error("A wallet with this address already exists in this browser.");
  }

  let passwordBytes = encodePassword(password);
  let privateKey: Uint8Array | null = null;
  try {
    privateKey = await openEnvelope(envelope, passwordBytes);
  } finally {
    zeroBuffer(passwordBytes);
  }

  try {
    zeroBuffer(privateKey);
  } catch {
    // privateKey already consumed by openEnvelope verification
  }

  await saveWallet(envelope);
  return envelope.address;
}
