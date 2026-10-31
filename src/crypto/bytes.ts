const HEX_PATTERN = /^(?:[0-9a-f]{2})*$/;

export function bytesToHex(bytes: Uint8Array): string {
  let out = "";
  for (const byte of bytes) out += byte.toString(16).padStart(2, "0");
  return out;
}

export function hexToBytes(hex: string, expectedLength?: number): Uint8Array {
  if (!HEX_PATTERN.test(hex)) throw new Error("Invalid hex: must be lowercase and even length.");
  const bytes = new Uint8Array(hex.length / 2);
  for (let i = 0; i < bytes.length; i++) bytes[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  if (expectedLength !== undefined && bytes.length !== expectedLength) {
    throw new Error(`Invalid hex length: expected ${expectedLength} bytes.`);
  }
  return bytes;
}
