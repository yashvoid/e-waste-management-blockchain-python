import { describe, expect, it } from "vitest";
import vectors from "../../test-vectors/crypto-vectors.json";
import { bytesToHex, hexToBytes } from "./bytes";
import { DOMAIN_TAGS, domainHash } from "./hashing";
import {
  compressedPublicKeyFromPrivateKey,
  signDigest,
  verifyDigest,
} from "./secp256k1";

const { transaction } = vectors;
const digest = hexToBytes(transaction.digest_hex);

describe("transaction digest", () => {
  it("recomputes the transaction digest from the canonical body", () => {
    const recomputed = domainHash(DOMAIN_TAGS.transaction, new TextEncoder().encode(transaction.canonical_text));
    expect(bytesToHex(recomputed)).toBe(transaction.digest_hex);
  });
});

describe("secp256k1 signing (interoperability only)", () => {
  it("derives the test public key from the test private key", () => {
    const valid = vectors.signatures.find((entry) => entry.expected_valid);
    if (valid === undefined) throw new Error("Missing valid signature vector");
    expect(compressedPublicKeyFromPrivateKey(transaction.private_key_hex)).toBe(valid.public_key_hex);
  });

  it("produces the exact 64-byte low-S compact signature from the vector", () => {
    expect(signDigest(digest, transaction.private_key_hex)).toBe(transaction.signature_hex);
  });

  it("signs deterministically", () => {
    expect(signDigest(digest, transaction.private_key_hex)).toBe(signDigest(digest, transaction.private_key_hex));
  });
});

describe("secp256k1 verification against shared vectors", () => {
  for (const vector of vectors.signatures) {
    it(`${vector.expected_valid ? "accepts" : "rejects"}: ${vector.name}`, () => {
      expect(verifyDigest(vector.public_key_hex, hexToBytes(vector.digest_hex), vector.signature_hex)).toBe(
        vector.expected_valid,
      );
    });
  }

  it("rejects the signature when the transaction body is altered", () => {
    const altered = domainHash(DOMAIN_TAGS.transaction, new TextEncoder().encode(transaction.altered_canonical_text));
    expect(bytesToHex(altered)).toBe(transaction.altered_digest_hex);
    const [valid] = vectors.signatures;
    expect(verifyDigest(valid.public_key_hex, altered, transaction.signature_hex)).toBe(false);
  });
});
