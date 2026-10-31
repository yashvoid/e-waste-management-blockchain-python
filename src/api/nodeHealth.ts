export type ConnectionState =
  | { kind: "checking" }
  | { kind: "connected" }
  | { kind: "unavailable"; reason: string };

const HEALTH_PATH = "/api/health";

export const UNREACHABLE_MESSAGE =
  "This node could not be reached. Check that the node is running, then try again.";
export const UNEXPECTED_RESPONSE_MESSAGE = "The node responded, but not as expected.";

export async function checkNodeHealth(fetchFn: typeof fetch = fetch): Promise<ConnectionState> {
  let response: Response;
  try {
    response = await fetchFn(HEALTH_PATH, { headers: { Accept: "application/json" } });
  } catch {
    return { kind: "unavailable", reason: UNREACHABLE_MESSAGE };
  }

  if (!response.ok) {
    return { kind: "unavailable", reason: UNREACHABLE_MESSAGE };
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return { kind: "unavailable", reason: UNEXPECTED_RESPONSE_MESSAGE };
  }

  if (isHealthyBody(body)) {
    return { kind: "connected" };
  }
  return { kind: "unavailable", reason: UNEXPECTED_RESPONSE_MESSAGE };
}

function isHealthyBody(body: unknown): boolean {
  return typeof body === "object" && body !== null && (body as { status?: unknown }).status === "ok";
}
