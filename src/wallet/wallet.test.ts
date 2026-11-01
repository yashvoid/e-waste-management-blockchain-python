import { describe, expect, it, beforeEach, vi, afterEach } from "vitest";
import "fake-indexeddb/auto";
import { bytesToHex } from "../crypto/bytes";
import { domainHash, DOMAIN_TAGS } from "../crypto/hashing";
import { generateWalletKeyPair, derivePublicKeyAndAddress } from "./keyGeneration";
import {
  SALT_LENGTH,
  NONCE_LENGTH,
  CIPHERTEXT_LENGTH,
  zeroBuffer,
  randomBytes,
  deriveEncryptionKey,
  encryptPrivateKey,
  decryptPrivateKey,
} from "./encryption";
import {
  createEnvelope,
  openEnvelope,
  validateEnvelope,
  type WalletEnvelope,
  UnsupportedWalletFormatError,
} from "./walletEnvelope";
import {
  saveWallet,
  loadWallet,
  listWalletAddresses,
  deleteWallet,
  _resetDatabaseConnection,
} from "./walletStore";
import {
  createWallet,
  unlock,
  lock,
  isUnlocked,
  getUnlockedAddress,
  sign,
  _resetSession,
  WalletLockedError,
  exportWalletBackup,
  importWalletBackup,
} from "./walletSession";
import {
  deserializeEnvelope,
  BACKUP_FORMAT_VERSION,
  BACKUP_MAGIC,
  type BackupFile,
} from "./backupFormat";

const VALID_PASSWORD = "test-password-12";

async function makeStoredWallet(
  password: string = VALID_PASSWORD,
): Promise<{ address: string; envelope: WalletEnvelope }> {
  const generated = generateWalletKeyPair();
  const envelope = await createEnvelope(
    generated.privateKey,
    generated.publicKeyHex,
    generated.address,
    new TextEncoder().encode(password),
  );
  zeroBuffer(generated.privateKey);
  await saveWallet(envelope);
  return { address: generated.address, envelope };
}

beforeEach(() => {
  _resetDatabaseConnection();
  _resetSession();
});

afterEach(() => {
  _resetSession();
  vi.useRealTimers();
});

describe("wallet generation", () => {
  it("generates a valid 32-byte private key", () => {
    const { privateKey } = generateWalletKeyPair();
    expect(privateKey).toBeInstanceOf(Uint8Array);
    expect(privateKey.length).toBe(32);
    expect(privateKey.every((b) => b === 0)).toBe(false);
  });

  it("derives a valid compressed public key and address", () => {
    const { publicKeyHex, address } = generateWalletKeyPair();
    expect(publicKeyHex).toMatch(/^0[23][0-9a-f]{64}$/);
    expect(address).toMatch(/^[0-9a-f]{40}$/);
  });

  it("produces different keys on independent generations", () => {
    const a = generateWalletKeyPair();
    const b = generateWalletKeyPair();
    expect(bytesToHex(a.privateKey)).not.toBe(bytesToHex(b.privateKey));
  });

  it("re-derives matching public key and address from the same private key", () => {
    const generated = generateWalletKeyPair();
    const rederived = derivePublicKeyAndAddress(generated.privateKey);
    expect(rederived.publicKeyHex).toBe(generated.publicKeyHex);
    expect(rederived.address).toBe(generated.address);
  });
});

describe("encryption", () => {
  it("round-trips encrypt and decrypt with the correct password", async () => {
    const salt = randomBytes(SALT_LENGTH);
    const nonce = randomBytes(NONCE_LENGTH);
    const privateKey = randomBytes(32);
    const aad = new Uint8Array([1, 2, 3]);
    const key = await deriveEncryptionKey(new TextEncoder().encode("password-12345"), salt);
    const ciphertext = encryptPrivateKey(key, nonce, privateKey, aad);
    expect(ciphertext.length).toBe(CIPHERTEXT_LENGTH);
    const decrypted = decryptPrivateKey(key, nonce, ciphertext, aad);
    expect(bytesToHex(decrypted)).toBe(bytesToHex(privateKey));
    zeroBuffer(key);
    zeroBuffer(privateKey);
  });

  it("fails with a wrong password (generic unlock error)", async () => {
    const salt = randomBytes(SALT_LENGTH);
    const nonce = randomBytes(NONCE_LENGTH);
    const privateKey = randomBytes(32);
    const aad = new Uint8Array([1, 2, 3]);
    const key1 = await deriveEncryptionKey(new TextEncoder().encode("password-12345"), salt);
    const ciphertext = encryptPrivateKey(key1, nonce, privateKey, aad);
    const key2 = await deriveEncryptionKey(new TextEncoder().encode("wrong-password-x"), salt);
    expect(() => decryptPrivateKey(key2, nonce, ciphertext, aad)).toThrow();
    zeroBuffer(key1);
    zeroBuffer(key2);
    zeroBuffer(privateKey);
  });

  it("fails when ciphertext is tampered", async () => {
    const salt = randomBytes(SALT_LENGTH);
    const nonce = randomBytes(NONCE_LENGTH);
    const privateKey = randomBytes(32);
    const aad = new Uint8Array([1, 2, 3]);
    const key = await deriveEncryptionKey(new TextEncoder().encode("password-12345"), salt);
    const ciphertext = encryptPrivateKey(key, nonce, privateKey, aad);
    ciphertext[0] ^= 0xff;
    expect(() => decryptPrivateKey(key, nonce, ciphertext, aad)).toThrow();
    zeroBuffer(key);
    zeroBuffer(privateKey);
  });

  it("fails when nonce is tampered", async () => {
    const salt = randomBytes(SALT_LENGTH);
    const nonce = randomBytes(NONCE_LENGTH);
    const privateKey = randomBytes(32);
    const aad = new Uint8Array([1, 2, 3]);
    const key = await deriveEncryptionKey(new TextEncoder().encode("password-12345"), salt);
    const ciphertext = encryptPrivateKey(key, nonce, privateKey, aad);
    nonce[0] ^= 0xff;
    expect(() => decryptPrivateKey(key, nonce, ciphertext, aad)).toThrow();
    zeroBuffer(key);
    zeroBuffer(privateKey);
  });

  it("fails when AAD is tampered", async () => {
    const salt = randomBytes(SALT_LENGTH);
    const nonce = randomBytes(NONCE_LENGTH);
    const privateKey = randomBytes(32);
    const aad = new Uint8Array([1, 2, 3]);
    const key = await deriveEncryptionKey(new TextEncoder().encode("password-12345"), salt);
    const ciphertext = encryptPrivateKey(key, nonce, privateKey, aad);
    const tamperedAad = new Uint8Array([1, 2, 4]);
    expect(() => decryptPrivateKey(key, nonce, ciphertext, tamperedAad)).toThrow();
    zeroBuffer(key);
    zeroBuffer(privateKey);
  });

  it("different salts produce different ciphertexts", async () => {
    const salt1 = randomBytes(SALT_LENGTH);
    const salt2 = randomBytes(SALT_LENGTH);
    const nonce = randomBytes(NONCE_LENGTH);
    const privateKey = randomBytes(32);
    const aad = new Uint8Array([1, 2, 3]);
    const key1 = await deriveEncryptionKey(new TextEncoder().encode("password-12345"), salt1);
    const key2 = await deriveEncryptionKey(new TextEncoder().encode("password-12345"), salt2);
    const ct1 = encryptPrivateKey(key1, nonce, privateKey, aad);
    const ct2 = encryptPrivateKey(key2, nonce, privateKey, aad);
    expect(bytesToHex(ct1)).not.toBe(bytesToHex(ct2));
    zeroBuffer(key1);
    zeroBuffer(key2);
    zeroBuffer(privateKey);
  });
});

describe("buffer clearing helper", () => {
  it("zeros a non-zero Uint8Array", () => {
    const buf = new Uint8Array([1, 2, 3, 4, 5]);
    zeroBuffer(buf);
    expect(buf.every((b) => b === 0)).toBe(true);
  });

  it("is a no-op on an already-zero array", () => {
    const buf = new Uint8Array(8);
    zeroBuffer(buf);
    expect(buf.every((b) => b === 0)).toBe(true);
  });
});

describe("password validation", () => {
  it("rejects fewer than 12 Unicode code points", async () => {
    await expect(createWallet("short")).rejects.toThrow();
  });

  it("rejects more than 1024 UTF-8 bytes", async () => {
    const longPw = "a".repeat(1025);
    await expect(createWallet(longPw)).rejects.toThrow();
  });

  it("accepts a multibyte password and unlocks consistently", async () => {
    const mbPassword = "пароль-тест-12";
    const address = await createWallet(mbPassword);
    await unlock(address, mbPassword);
    expect(isUnlocked()).toBe(true);
  });

  it("rejects unpaired surrogates", async () => {
    await expect(createWallet("password-12\uD800")).rejects.toThrow();
  });
});

describe("envelope validation", () => {
  let validEnvelope: WalletEnvelope;

  beforeEach(async () => {
    const result = await makeStoredWallet();
    validEnvelope = result.envelope;
  });

  it("accepts a valid envelope", () => {
    expect(() => validateEnvelope(validEnvelope)).not.toThrow();
  });

  it("rejects unsupported version before KDF", () => {
    const bad = { ...validEnvelope, version: 99 };
    expect(() => validateEnvelope(bad)).toThrow(UnsupportedWalletFormatError);
  });

  it("rejects unsupported KDF before KDF", () => {
    const bad = { ...validEnvelope, kdf: "argon2" };
    expect(() => validateEnvelope(bad)).toThrow(UnsupportedWalletFormatError);
  });

  it("rejects unsupported cipher before KDF", () => {
    const bad = { ...validEnvelope, cipher: "chacha20" };
    expect(() => validateEnvelope(bad)).toThrow(UnsupportedWalletFormatError);
  });

  it("rejects incorrect scrypt parameters before KDF", () => {
    const bad = { ...validEnvelope, scryptParams: { N: 32768, r: 8, p: 1 } };
    expect(() => validateEnvelope(bad)).toThrow(UnsupportedWalletFormatError);
  });

  it("rejects invalid salt length before KDF", () => {
    const bad = { ...validEnvelope, salt: new Uint8Array(15) };
    expect(() => validateEnvelope(bad)).toThrow(UnsupportedWalletFormatError);
  });

  it("rejects invalid nonce length before KDF", () => {
    const bad = { ...validEnvelope, nonce: new Uint8Array(11) };
    expect(() => validateEnvelope(bad)).toThrow(UnsupportedWalletFormatError);
  });

  it("rejects invalid ciphertext length before KDF", () => {
    const bad = { ...validEnvelope, ciphertext: new Uint8Array(47) };
    expect(() => validateEnvelope(bad)).toThrow(UnsupportedWalletFormatError);
  });

  it("rejects malformed public key before KDF", () => {
    const bad = { ...validEnvelope, publicKey: "zz" + validEnvelope.publicKey.slice(2) };
    expect(() => validateEnvelope(bad)).toThrow(UnsupportedWalletFormatError);
  });

  it("rejects malformed address before KDF", () => {
    const bad = { ...validEnvelope, address: "zz" + validEnvelope.address.slice(2) };
    expect(() => validateEnvelope(bad)).toThrow(UnsupportedWalletFormatError);
  });

  it("rejects missing createdAt before KDF", () => {
    const bad = { ...validEnvelope, createdAt: undefined };
    expect(() => validateEnvelope(bad)).toThrow(UnsupportedWalletFormatError);
  });

  it("does not invoke scrypt for invalid envelopes", async () => {
    const bad = { ...validEnvelope, version: 99 } as unknown as WalletEnvelope;
    const start = performance.now();
    await expect(openEnvelope(bad, new TextEncoder().encode(VALID_PASSWORD))).rejects.toThrow(
      UnsupportedWalletFormatError,
    );
    const elapsed = performance.now() - start;
    // scrypt takes >50ms; if validation rejected before KDF, this returns in <5ms
    expect(elapsed).toBeLessThan(50);
  });
});

describe("post-decryption verification", () => {
  it("re-derives a matching public key and address", async () => {
    const { address, envelope } = await makeStoredWallet();
    const privateKey = await openEnvelope(envelope, new TextEncoder().encode(VALID_PASSWORD));
    const { publicKeyHex, address: rederivedAddress } = derivePublicKeyAndAddress(privateKey);
    expect(publicKeyHex).toBe(envelope.publicKey);
    expect(rederivedAddress).toBe(address);
    zeroBuffer(privateKey);
  });

  it("rejects a mismatched public key as corruption", async () => {
    const { envelope } = await makeStoredWallet();
    const generated = generateWalletKeyPair();
    const tampered = { ...envelope, publicKey: generated.publicKeyHex, address: generated.address };
    zeroBuffer(generated.privateKey);
    await expect(openEnvelope(tampered, new TextEncoder().encode(VALID_PASSWORD))).rejects.toThrow();
  });
});

describe("IndexedDB storage", () => {
  it("persists a wallet across a simulated reload", async () => {
    const { address, envelope } = await makeStoredWallet();
    _resetDatabaseConnection();
    const loaded = await loadWallet(address);
    expect(loaded).toBeDefined();
    expect(loaded!.address).toBe(address);
    expect(loaded!.publicKey).toBe(envelope.publicKey);
  });

  it("supports multiple wallets coexisting", async () => {
    const a = await makeStoredWallet();
    const b = await makeStoredWallet();
    const addresses = await listWalletAddresses();
    expect(addresses).toContain(a.address);
    expect(addresses).toContain(b.address);
  });

  it("deletes a wallet", async () => {
    const { address } = await makeStoredWallet();
    await deleteWallet(address);
    const loaded = await loadWallet(address);
    expect(loaded).toBeUndefined();
  });

  it("does not store plaintext private keys or passwords", async () => {
    const { envelope } = await makeStoredWallet();
    const envelopeStr = JSON.stringify(envelope, (_key, value) => {
      if (value instanceof Uint8Array) return bytesToHex(value);
      return value;
    });
    expect(envelopeStr).not.toContain(VALID_PASSWORD);
    expect(envelope.ciphertext.length).toBe(CIPHERTEXT_LENGTH);
  });
});

describe("wallet session (real timers)", () => {
  it("signs a digest while unlocked", async () => {
    const address = await createWallet(VALID_PASSWORD);
    await unlock(address, VALID_PASSWORD);
    expect(isUnlocked()).toBe(true);
    const digest = domainHash(DOMAIN_TAGS.transaction, new TextEncoder().encode("{}"));
    const signature = sign(digest);
    expect(signature).toMatch(/^[0-9a-f]{128}$/);
  });

  it("manual lock prevents subsequent signing", async () => {
    const address = await createWallet(VALID_PASSWORD);
    await unlock(address, VALID_PASSWORD);
    lock();
    expect(isUnlocked()).toBe(false);
    const digest = new Uint8Array(32);
    expect(() => sign(digest)).toThrow(WalletLockedError);
  });

  it("hidden page event locks immediately", async () => {
    if (typeof document === "undefined") return;
    const address = await createWallet(VALID_PASSWORD);
    await unlock(address, VALID_PASSWORD);
    expect(isUnlocked()).toBe(true);
    Object.defineProperty(document, "hidden", { value: true, configurable: true, writable: true });
    document.dispatchEvent(new Event("visibilitychange"));
    expect(isUnlocked()).toBe(false);
    Object.defineProperty(document, "hidden", { value: false, configurable: true, writable: true });
  });

  it("rejects an invalid digest length", async () => {
    const address = await createWallet(VALID_PASSWORD);
    await unlock(address, VALID_PASSWORD);
    expect(() => sign(new Uint8Array(31))).toThrow();
  });

  it("does not expose a raw private key through any public method", async () => {
    const session = (await import("./walletSession")) as unknown as Record<string, unknown>;
    expect(typeof session.getPrivateKeyHex).toBe("undefined");
    expect(typeof session.getPrivateKey).toBe("undefined");
    expect(typeof session.getPrivateKeyBytes).toBe("undefined");
  });

  it("spaces are significant in passwords (no trimming)", async () => {
    const passwordWithSpaces = "  test-password-12  ";
    const address = await createWallet(passwordWithSpaces);
    await unlock(address, passwordWithSpaces);
    expect(isUnlocked()).toBe(true);
    lock();
    await expect(unlock(address, "test-password-12")).rejects.toThrow();
  });

  it("wrong password fails to unlock", async () => {
    const address = await createWallet(VALID_PASSWORD);
    await expect(unlock(address, "wrong-password-x")).rejects.toThrow();
    expect(isUnlocked()).toBe(false);
  });

  it("does not leave a decrypted key when unlock fails", async () => {
    const address = await createWallet(VALID_PASSWORD);
    try {
      await unlock(address, "wrong-password-x");
    } catch {
      // expected
    }
    expect(isUnlocked()).toBe(false);
  });

  it("does not retain session state when creating a wallet that fails", async () => {
    await expect(createWallet("short")).rejects.toThrow();
    expect(isUnlocked()).toBe(false);
  });

  it("returns the unlocked address", async () => {
    const address = await createWallet(VALID_PASSWORD);
    await unlock(address, VALID_PASSWORD);
    expect(getUnlockedAddress()).toBe(address);
  });

  it("returns null address when locked", () => {
    expect(getUnlockedAddress()).toBeNull();
  });
});

describe("wallet session inactivity", () => {
  it("locks when the inactivity deadline passes (time-check in sign)", async () => {
    const address = await createWallet(VALID_PASSWORD);
    await unlock(address, VALID_PASSWORD);
    const realNow = performance.now;
    const baseTime = realNow.call(performance);
    performance.now = vi.fn(() => baseTime + 15 * 60 * 1000 + 1) as unknown as typeof performance.now;
    expect(() => sign(new Uint8Array(32))).toThrow(WalletLockedError);
    expect(isUnlocked()).toBe(false);
    performance.now = realNow;
  });

  it("successful signing resets the inactivity period", async () => {
    const address = await createWallet(VALID_PASSWORD);
    await unlock(address, VALID_PASSWORD);
    const realNow = performance.now;
    const baseTime = realNow.call(performance);
    // 14 min since unlock — still unlocked
    performance.now = vi.fn(() => baseTime + 14 * 60 * 1000) as unknown as typeof performance.now;
    sign(new Uint8Array(32));
    // 2 more min since last sign (16 min total) — still within 15 min of last sign
    performance.now = vi.fn(() => baseTime + 16 * 60 * 1000) as unknown as typeof performance.now;
    expect(isUnlocked()).toBe(true);
    performance.now = realNow;
  });

  it("setTimeout safety net locks the wallet after the inactivity period", async () => {
    const address = await createWallet(VALID_PASSWORD);

    let autoLockFn: (() => void) | null = null;
    const realSetTimeout = globalThis.setTimeout;
    const spy = vi.spyOn(globalThis, "setTimeout").mockImplementation((fn: any, delay?: number) => {
      if (delay === 15 * 60 * 1000) {
        autoLockFn = fn as () => void;
      }
      return realSetTimeout(fn as TimerHandler, delay) as unknown as ReturnType<typeof setTimeout>;
    });

    await unlock(address, VALID_PASSWORD);
    spy.mockRestore();

    expect(autoLockFn).not.toBeNull();
    expect(isUnlocked()).toBe(true);
    autoLockFn!();
    expect(isUnlocked()).toBe(false);
  });
});

describe("measured scrypt performance", () => {
  it("measures scrypt derivation time", async () => {
    const salt = randomBytes(SALT_LENGTH);
    const start = performance.now();
    const key = await deriveEncryptionKey(new TextEncoder().encode(VALID_PASSWORD), salt);
    const elapsed = performance.now() - start;
    expect(key.length).toBe(32);
    expect(elapsed).toBeGreaterThan(0);
    expect(elapsed).toBeLessThan(5000);
    zeroBuffer(key);
  });
});

describe("wallet backup export", () => {
  it("export produces a valid backup file", async () => {
    const { address } = await makeStoredWallet();
    const { content, filename } = await exportWalletBackup(address);
    expect(filename).toMatch(/^wallet-[0-9a-f]{8}\.ewallet$/);
    const parsed = JSON.parse(content);
    expect(parsed.format).toBe(BACKUP_MAGIC);
    expect(parsed.backupVersion).toBe(BACKUP_FORMAT_VERSION);
    expect(parsed.envelope).toBeDefined();
  });

  it("export preserves the original encrypted envelope", async () => {
    const { address, envelope } = await makeStoredWallet();
    const { content } = await exportWalletBackup(address);
    const parsed = JSON.parse(content) as BackupFile;
    const restored = deserializeEnvelope(parsed.envelope);
    expect(bytesToHex(restored.salt)).toBe(bytesToHex(envelope.salt));
    expect(bytesToHex(restored.nonce)).toBe(bytesToHex(envelope.nonce));
    expect(bytesToHex(restored.ciphertext)).toBe(bytesToHex(envelope.ciphertext));
    expect(restored.publicKey).toBe(envelope.publicKey);
    expect(restored.address).toBe(envelope.address);
    expect(restored.version).toBe(envelope.version);
    expect(restored.kdf).toBe(envelope.kdf);
    expect(restored.cipher).toBe(envelope.cipher);
    expect(restored.scryptParams).toEqual(envelope.scryptParams);
    expect(restored.createdAt).toBe(envelope.createdAt);
  });

  it("export fails for a non-existent wallet", async () => {
    await expect(exportWalletBackup("0000000000000000000000000000000000000000")).rejects.toThrow();
  });

  it("export does not include plaintext private key or password", async () => {
    const { address } = await makeStoredWallet();
    const { content } = await exportWalletBackup(address);
    expect(content).not.toContain(VALID_PASSWORD);
    const parsed = JSON.parse(content) as BackupFile;
    expect(parsed.envelope.ciphertext).not.toHaveLength(0);
    expect(parsed.envelope).not.toHaveProperty("privateKey");
  });
});

describe("wallet backup import and restoration", () => {
  it("import reconstructs the correct envelope and binary fields", async () => {
    const { address, envelope } = await makeStoredWallet();
    const { content } = await exportWalletBackup(address);
    await deleteWallet(address);
    const restoredAddress = await importWalletBackup(content, VALID_PASSWORD);
    expect(restoredAddress).toBe(address);
    const loaded = await loadWallet(address);
    expect(loaded).toBeDefined();
    expect(bytesToHex(loaded!.salt)).toBe(bytesToHex(envelope.salt));
    expect(bytesToHex(loaded!.nonce)).toBe(bytesToHex(envelope.nonce));
    expect(bytesToHex(loaded!.ciphertext)).toBe(bytesToHex(envelope.ciphertext));
    expect(loaded!.publicKey).toBe(envelope.publicKey);
  });

  it("correct password restores the original wallet identity", async () => {
    const { address } = await makeStoredWallet();
    const { content } = await exportWalletBackup(address);
    await deleteWallet(address);
    await importWalletBackup(content, VALID_PASSWORD);
    const loaded = await loadWallet(address);
    expect(loaded).toBeDefined();
    expect(loaded!.address).toBe(address);
  });

  it("restored wallet can be unlocked and sign successfully", async () => {
    const { address } = await makeStoredWallet();
    const { content } = await exportWalletBackup(address);
    await deleteWallet(address);
    await importWalletBackup(content, VALID_PASSWORD);
    await unlock(address, VALID_PASSWORD);
    expect(isUnlocked()).toBe(true);
    const digest = domainHash(DOMAIN_TAGS.transaction, new TextEncoder().encode("{}"));
    const signature = sign(digest);
    expect(signature).toMatch(/^[0-9a-f]{128}$/);
  });

  it("incorrect password is rejected", async () => {
    const { address } = await makeStoredWallet();
    const { content } = await exportWalletBackup(address);
    await deleteWallet(address);
    await expect(importWalletBackup(content, "wrong-password-x")).rejects.toThrow();
  });

  it("malformed backup is rejected", async () => {
    await expect(importWalletBackup("not json at all", VALID_PASSWORD)).rejects.toThrow();
    await expect(importWalletBackup('{"random":"data"}', VALID_PASSWORD)).rejects.toThrow();
    await expect(importWalletBackup('{"format":"wrong","backupVersion":1}', VALID_PASSWORD)).rejects.toThrow();
  });

  it("unsupported backup version is rejected", async () => {
    const { address } = await makeStoredWallet();
    const { content } = await exportWalletBackup(address);
    const parsed = JSON.parse(content) as BackupFile;
    parsed.backupVersion = 99;
    await expect(importWalletBackup(JSON.stringify(parsed), VALID_PASSWORD)).rejects.toThrow(
      "Unsupported backup version",
    );
  });

  it("tampered encrypted backup is rejected", async () => {
    const { address } = await makeStoredWallet();
    const { content } = await exportWalletBackup(address);
    await deleteWallet(address);
    const parsed = JSON.parse(content) as BackupFile;
    const tamperedCipher = parsed.envelope.ciphertext.slice(0, -4) + "ffff";
    parsed.envelope.ciphertext = tamperedCipher;
    await expect(importWalletBackup(JSON.stringify(parsed), VALID_PASSWORD)).rejects.toThrow();
  });

  it("duplicate local wallet address is rejected without overwriting existing storage", async () => {
    const { address, envelope } = await makeStoredWallet();
    const { content } = await exportWalletBackup(address);
    await expect(importWalletBackup(content, VALID_PASSWORD)).rejects.toThrow(
      "already exists",
    );
    const loaded = await loadWallet(address);
    expect(loaded).toBeDefined();
    expect(bytesToHex(loaded!.ciphertext)).toBe(bytesToHex(envelope.ciphertext));
  });

  it("failed import does not modify existing wallet storage", async () => {
    const { address, envelope } = await makeStoredWallet();
    const { content } = await exportWalletBackup(address);
    const otherWallet = await makeStoredWallet();
    const otherLoaded = await loadWallet(otherWallet.address);
    expect(otherLoaded).toBeDefined();

    const parsed = JSON.parse(content) as BackupFile;
    parsed.envelope.publicKey = "0" + parsed.envelope.publicKey.slice(1) === parsed.envelope.publicKey
      ? "02" + "f".repeat(64)
      : "03" + "f".repeat(64);
    parsed.envelope.address = "f".repeat(40);

    await expect(importWalletBackup(JSON.stringify(parsed), VALID_PASSWORD)).rejects.toThrow();

    const existingLoaded = await loadWallet(address);
    expect(existingLoaded).toBeDefined();
    expect(bytesToHex(existingLoaded!.ciphertext)).toBe(bytesToHex(envelope.ciphertext));
  });
});
