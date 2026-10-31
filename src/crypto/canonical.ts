export type CanonicalValue = string | number | boolean | null | CanonicalValue[] | { [key: string]: CanonicalValue };

const MAX_DEPTH = 32;
const LONE_SURROGATE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/;
const encoder = new TextEncoder();

export function canonicalText(value: unknown): string {
  return encodeValue(value, 0);
}

export function canonicalBytes(value: unknown): Uint8Array {
  return encoder.encode(canonicalText(value));
}

function encodeValue(value: unknown, depth: number): string {
  if (typeof value === "string") return encodeString(value);
  if (value === null) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") {
    if (!Number.isSafeInteger(value) || Object.is(value, -0)) {
      throw new Error("Canonical numbers must be safe integers.");
    }
    return String(value);
  }
  if (Array.isArray(value)) {
    checkDepth(depth + 1);
    return `[${Array.from(value, (item) => encodeValue(item, depth + 1)).join(",")}]`;
  }
  if (typeof value === "object") {
    const prototype = Object.getPrototypeOf(value);
    if (prototype !== Object.prototype && prototype !== null) {
      throw new Error("Canonical objects must be plain objects.");
    }
    checkDepth(depth + 1);
    const record = value as Record<string, unknown>;
    const entries = Object.keys(record).map((key) => ({
      key: encodeString(key),
      sortKey: encoder.encode(key),
      value: record[key],
    }));
    entries.sort((a, b) => compareBytes(a.sortKey, b.sortKey));
    const members = entries.map((entry) => `${entry.key}:${encodeValue(entry.value, depth + 1)}`);
    return `{${members.join(",")}}`;
  }
  throw new Error("Unsupported value in canonical serialization.");
}

function encodeString(text: string): string {
  if (LONE_SURROGATE.test(text)) throw new Error("Strings must not contain lone surrogates.");
  if (text.normalize("NFC") !== text) throw new Error("Strings must be Unicode NFC normalized.");
  let out = '"';
  for (const char of text) {
    const code = char.codePointAt(0) ?? 0;
    if (char === '"') out += '\\"';
    else if (char === "\\") out += "\\\\";
    else if (code < 0x20) out += `\\u${code.toString(16).padStart(4, "0")}`;
    else out += char;
  }
  return `${out}"`;
}

function checkDepth(depth: number): void {
  if (depth > MAX_DEPTH) throw new Error("Nesting depth exceeds the limit.");
}

function compareBytes(a: Uint8Array, b: Uint8Array): number {
  const length = Math.min(a.length, b.length);
  for (let i = 0; i < length; i++) {
    if (a[i] !== b[i]) return a[i] - b[i];
  }
  return a.length - b.length;
}
