import type { CanonicalValue } from "./canonical";

const MAX_DEPTH = 32;
const NUMBER_TOKEN = /-?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/y;
const INTEGER_TOKEN = /^-?(?:0|[1-9][0-9]*)$/;
const WHITESPACE = new Set([" ", "\t", "\n", "\r"]);
const SIMPLE_ESCAPES: Record<string, string> = {
  '"': '"',
  "\\": "\\",
  "/": "/",
  b: "\b",
  f: "\f",
  n: "\n",
  r: "\r",
  t: "\t",
};

export function parseStrictJsonBytes(bytes: Uint8Array): CanonicalValue {
  const text = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes);
  return new StrictJsonParser(text).parseDocument();
}

class StrictJsonParser {
  private pos = 0;

  constructor(private readonly text: string) {}

  parseDocument(): CanonicalValue {
    this.skipWhitespace();
    const value = this.parseValue(0);
    this.skipWhitespace();
    if (this.pos !== this.text.length) throw this.error("Unexpected content after the document.");
    return value;
  }

  private parseValue(depth: number): CanonicalValue {
    const char = this.text[this.pos];
    if (char === "{") return this.parseObject(depth + 1);
    if (char === "[") return this.parseArray(depth + 1);
    if (char === '"') return this.parseString();
    if (char === "t") return this.parseLiteral("true", true);
    if (char === "f") return this.parseLiteral("false", false);
    if (char === "n") return this.parseLiteral("null", null);
    if (char === "-" || (char !== undefined && char >= "0" && char <= "9")) return this.parseNumber();
    throw this.error("Unexpected token.");
  }

  private parseObject(depth: number): CanonicalValue {
    this.checkDepth(depth);
    this.pos++;
    const result: { [key: string]: CanonicalValue } = Object.create(null);
    const seen = new Set<string>();
    this.skipWhitespace();
    if (this.text[this.pos] === "}") {
      this.pos++;
      return result;
    }
    for (;;) {
      if (this.text[this.pos] !== '"') throw this.error("Object keys must be strings.");
      const key = this.parseString();
      if (seen.has(key)) throw this.error("Duplicate object key.");
      seen.add(key);
      this.skipWhitespace();
      this.expect(":");
      this.skipWhitespace();
      result[key] = this.parseValue(depth);
      this.skipWhitespace();
      if (this.text[this.pos] === ",") {
        this.pos++;
        this.skipWhitespace();
        continue;
      }
      this.expect("}");
      return result;
    }
  }

  private parseArray(depth: number): CanonicalValue {
    this.checkDepth(depth);
    this.pos++;
    const result: CanonicalValue[] = [];
    this.skipWhitespace();
    if (this.text[this.pos] === "]") {
      this.pos++;
      return result;
    }
    for (;;) {
      result.push(this.parseValue(depth));
      this.skipWhitespace();
      if (this.text[this.pos] === ",") {
        this.pos++;
        this.skipWhitespace();
        continue;
      }
      this.expect("]");
      return result;
    }
  }

  private parseString(): string {
    this.pos++;
    let out = "";
    for (;;) {
      const char = this.text[this.pos];
      if (char === undefined) throw this.error("Unterminated string.");
      if (char === '"') {
        this.pos++;
        return out;
      }
      if (char.charCodeAt(0) < 0x20) throw this.error("Raw control characters are not allowed in strings.");
      if (char !== "\\") {
        out += char;
        this.pos++;
        continue;
      }
      out += this.parseEscape();
    }
  }

  private parseEscape(): string {
    const escape = this.text[this.pos + 1];
    if (escape === undefined) throw this.error("Unterminated escape.");
    if (escape === "u") {
      const hex = this.text.slice(this.pos + 2, this.pos + 6);
      if (!/^[0-9a-fA-F]{4}$/.test(hex)) throw this.error("Invalid unicode escape.");
      this.pos += 6;
      return String.fromCharCode(parseInt(hex, 16));
    }
    const simple = SIMPLE_ESCAPES[escape];
    if (simple === undefined) throw this.error("Invalid escape sequence.");
    this.pos += 2;
    return simple;
  }

  private parseNumber(): number {
    NUMBER_TOKEN.lastIndex = this.pos;
    const match = NUMBER_TOKEN.exec(this.text);
    if (match === null) throw this.error("Invalid number.");
    const token = match[0];
    this.pos += token.length;
    if (!INTEGER_TOKEN.test(token)) throw this.error("Only integers are allowed.");
    if (token === "-0") throw this.error("Negative zero is not allowed.");
    const value = Number(token);
    if (!Number.isSafeInteger(value)) throw this.error("Integer is outside the safe range.");
    return value;
  }

  private parseLiteral<T extends CanonicalValue>(word: string, value: T): T {
    if (!this.text.startsWith(word, this.pos)) throw this.error("Invalid literal.");
    this.pos += word.length;
    return value;
  }

  private checkDepth(depth: number): void {
    if (depth > MAX_DEPTH) throw this.error("Nesting depth exceeds the limit.");
  }

  private expect(char: string): void {
    if (this.text[this.pos] !== char) throw this.error(`Expected "${char}".`);
    this.pos++;
  }

  private skipWhitespace(): void {
    while (this.pos < this.text.length && WHITESPACE.has(this.text[this.pos])) this.pos++;
  }

  private error(message: string): Error {
    return new Error(`Invalid JSON at position ${this.pos}: ${message}`);
  }
}
