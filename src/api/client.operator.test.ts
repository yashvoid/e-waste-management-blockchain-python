import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  getNodeInfo,
  OperatorSessionError,
  SESSION_ENDED_MESSAGE,
  signInOperator,
  signOutOperator,
} from "./client";
import { getOperatorToken, setOperatorToken } from "./operatorSession";

function memoryStorage(): Storage {
  const items = new Map<string, string>();
  return {
    getItem: (key: string) => items.get(key) ?? null,
    setItem: (key: string, value: string) => {
      items.set(key, String(value));
    },
    removeItem: (key: string) => {
      items.delete(key);
    },
    clear: () => items.clear(),
    key: (index: number) => [...items.keys()][index] ?? null,
    get length() {
      return items.size;
    },
  } as Storage;
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const NODE_INFO = {
  nodeId: "node-a",
  listenHost: "127.0.0.1",
  listenPort: 8000,
  peerPort: 8443,
  certificateSha256: "ab",
  networkId: "test",
  protocolVersion: 1,
  peers: [],
};

describe("operator session handling in the API client", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.stubGlobal("sessionStorage", memoryStorage());
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends the operator token as a bearer header on management calls", async () => {
    setOperatorToken("token-123");
    fetchMock.mockResolvedValue(jsonResponse(NODE_INFO));

    await expect(getNodeInfo()).resolves.toEqual(NODE_INFO);
    const [path, init] = fetchMock.mock.calls[0];
    expect(path).toBe("/api/node/info");
    expect((init as RequestInit).headers).toMatchObject({ Authorization: "Bearer token-123" });
  });

  it("refuses management calls without a token and makes no request", async () => {
    await expect(getNodeInfo()).rejects.toBeInstanceOf(OperatorSessionError);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("treats an unauthorized response as an ended session and clears the token", async () => {
    setOperatorToken("expired-token");
    fetchMock.mockResolvedValue(jsonResponse({ detail: "Operator sign-in is required." }, 401));

    const error = await getNodeInfo().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(OperatorSessionError);
    expect((error as Error).message).toBe(SESSION_ENDED_MESSAGE);
    expect(getOperatorToken()).toBeNull();
  });

  it("keeps the token when a request is forbidden for a non-session reason", async () => {
    setOperatorToken("token-123");
    fetchMock.mockResolvedValue(jsonResponse({ detail: "Forbidden" }, 403));

    await expect(getNodeInfo()).rejects.toThrow("Forbidden");
    expect(getOperatorToken()).toBe("token-123");
  });

  it("signs in by posting the password in the body and returns the token", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ token: "new-token", idleTimeoutSeconds: 900 }));

    const result = await signInOperator("operator-secret-value");
    expect(result).toEqual({ token: "new-token", idleTimeoutSeconds: 900 });
    const [path, init] = fetchMock.mock.calls[0];
    expect(path).toBe("/api/node/session");
    expect(String(path)).not.toContain("operator-secret-value");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ password: "operator-secret-value" });
  });

  it("reports a wrong password from sign-in as an ordinary error", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "The operator password is incorrect." }, 401));

    await expect(signInOperator("wrong-password-value")).rejects.toThrow("The operator password is incorrect.");
  });

  it("signs out by revoking the token on the node and clearing it locally", async () => {
    setOperatorToken("token-123");
    fetchMock.mockResolvedValue(jsonResponse({ signedOut: true }));

    await signOutOperator();
    const [path, init] = fetchMock.mock.calls[0];
    expect(path).toBe("/api/node/session");
    expect((init as RequestInit).method).toBe("DELETE");
    expect((init as RequestInit).headers).toMatchObject({ Authorization: "Bearer token-123" });
    expect(getOperatorToken()).toBeNull();
  });

  it("clears the token locally even when the node cannot be reached during sign-out", async () => {
    setOperatorToken("token-123");
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));

    await expect(signOutOperator()).resolves.toBeUndefined();
    expect(getOperatorToken()).toBeNull();
  });

  it("sign-out without a token makes no request", async () => {
    await signOutOperator();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
