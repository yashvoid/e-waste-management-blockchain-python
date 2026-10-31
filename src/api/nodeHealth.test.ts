import { describe, expect, it, vi } from "vitest";
import {
  checkNodeHealth,
  UNEXPECTED_RESPONSE_MESSAGE,
  UNREACHABLE_MESSAGE,
} from "./nodeHealth";

function fetchReturning(response: Response) {
  return vi.fn(async () => response) as unknown as typeof fetch;
}

describe("checkNodeHealth", () => {
  it("reports connected when the node answers with status ok", async () => {
    const fetchFn = fetchReturning(
      new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(checkNodeHealth(fetchFn)).resolves.toEqual({ kind: "connected" });
    expect(fetchFn).toHaveBeenCalledWith("/api/health", expect.any(Object));
  });

  it("reports unavailable when the request itself fails", async () => {
    const fetchFn = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    }) as unknown as typeof fetch;

    await expect(checkNodeHealth(fetchFn)).resolves.toEqual({
      kind: "unavailable",
      reason: UNREACHABLE_MESSAGE,
    });
  });

  it("reports unavailable when the proxy or node returns an error status", async () => {
    const fetchFn = fetchReturning(new Response("Bad gateway", { status: 502 }));

    await expect(checkNodeHealth(fetchFn)).resolves.toEqual({
      kind: "unavailable",
      reason: UNREACHABLE_MESSAGE,
    });
  });

  it("reports unavailable when the body is not valid JSON", async () => {
    const fetchFn = fetchReturning(new Response("<html></html>", { status: 200 }));

    await expect(checkNodeHealth(fetchFn)).resolves.toEqual({
      kind: "unavailable",
      reason: UNEXPECTED_RESPONSE_MESSAGE,
    });
  });

  it("reports unavailable when the body does not confirm health", async () => {
    const fetchFn = fetchReturning(
      new Response(JSON.stringify({ status: "starting" }), { status: 200 }),
    );

    await expect(checkNodeHealth(fetchFn)).resolves.toEqual({
      kind: "unavailable",
      reason: UNEXPECTED_RESPONSE_MESSAGE,
    });
  });
});
