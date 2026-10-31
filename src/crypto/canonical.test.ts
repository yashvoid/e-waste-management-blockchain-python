import { describe, expect, it } from "vitest";
import vectors from "../../test-vectors/crypto-vectors.json";
import { bytesToHex } from "./bytes";
import { canonicalBytes, canonicalText } from "./canonical";
import { parseStrictJsonBytes } from "./strictJson";

const encoder = new TextEncoder();

function canonicalizeText(text: string): string {
  return canonicalText(parseStrictJsonBytes(encoder.encode(text)));
}

describe("canonical serialization", () => {
  for (const vector of vectors.canonical_valid) {
    it(`matches the shared vector: ${vector.name}`, () => {
      expect(canonicalizeText(vector.input_text)).toBe(vector.canonical_text);
      expect(bytesToHex(canonicalBytes(parseStrictJsonBytes(encoder.encode(vector.input_text))))).toBe(
        vector.canonical_hex,
      );
    });
  }

  for (const vector of vectors.canonical_invalid) {
    it(`rejects: ${vector.name}`, () => {
      expect(() => canonicalizeText(vector.input)).toThrow();
    });
  }

  it("rejects a non-NFC string built in code rather than parsed", () => {
    expect(() => canonicalText({ a: "e\u0301" })).toThrow();
  });

  it("rejects a lone surrogate built in code rather than parsed", () => {
    expect(() => canonicalText({ a: "\ud800" })).toThrow();
  });

  it("rejects undefined, bigint and unsafe numbers built in code", () => {
    expect(() => canonicalText({ a: undefined })).toThrow();
    expect(() => canonicalText({ a: BigInt(1) })).toThrow();
    expect(() => canonicalText({ a: 2 ** 53 })).toThrow();
    expect(() => canonicalText({ a: -0 })).toThrow();
  });

  it("rejects non-plain objects built in code", () => {
    expect(() => canonicalText(new Date(0))).toThrow();
  });
});
