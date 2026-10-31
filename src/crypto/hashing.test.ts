import { describe, expect, it } from "vitest";
import vectors from "../../test-vectors/crypto-vectors.json";
import { bytesToHex, hexToBytes } from "./bytes";
import { domainHash, DOMAIN_TAGS, sha256 } from "./hashing";
import { walletAddressFromPublicKey } from "./secp256k1";

describe("SHA-256", () => {
  for (const vector of vectors.sha256) {
    it(`hashes input ${vector.input_hex === "" ? "(empty)" : vector.input_hex}`, () => {
      expect(bytesToHex(sha256(hexToBytes(vector.input_hex)))).toBe(vector.output_hex);
    });
  }
});

describe("domain-separated hashing", () => {
  for (const vector of vectors.domain_hash) {
    it(`hashes payload under ${vector.tag}`, () => {
      const tag = Object.values(DOMAIN_TAGS).find((value) => value === vector.tag);
      if (tag === undefined) throw new Error(`Unknown tag ${vector.tag}`);
      expect(bytesToHex(domainHash(tag, hexToBytes(vector.payload_hex)))).toBe(vector.output_hex);
    });
  }

  it("produces different digests for the same payload under different tags", () => {
    const payload = hexToBytes("00");
    expect(bytesToHex(domainHash(DOMAIN_TAGS.transaction, payload))).not.toBe(
      bytesToHex(domainHash(DOMAIN_TAGS.block, payload)),
    );
  });
});

describe("wallet address", () => {
  for (const vector of vectors.addresses) {
    it(`derives the address for ${vector.name}`, () => {
      expect(walletAddressFromPublicKey(vector.public_key_hex)).toBe(vector.address_hex);
    });
  }

  it("rejects an uncompressed public key", () => {
    const uncompressed = vectors.signatures.find((entry) => entry.name === "uncompressed public key prefix 04");
    if (uncompressed === undefined) throw new Error("Missing uncompressed key vector");
    expect(() => walletAddressFromPublicKey(uncompressed.public_key_hex)).toThrow();
  });
});
