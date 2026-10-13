import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";

import { ApiError } from "@/lib/api/api-error";
import { buildApiUrl, serverFetch } from "@/lib/api/server";

const incomingHeaders = vi.hoisted(() => new Map<string, string>());

vi.mock("next/headers", () => ({
  headers: () => Promise.resolve(new Headers(Object.fromEntries(incomingHeaders))),
}));

const fetchMock = vi.fn<typeof fetch>();

const jsonResponse = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });

const statusSchema = z.object({ status: z.literal("ok") });

beforeEach(() => {
  incomingHeaders.clear();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("serverFetch", () => {
  it("builds API URLs from the server base URL", () => {
    expect(buildApiUrl("/v1/health")).toBe("http://localhost:8000/v1/health");
    expect(buildApiUrl("v1/health", "https://internal.motionile.test")).toBe(
      "https://internal.motionile.test/v1/health",
    );
  });

  it("forwards cookies and the request id and validates the response", async () => {
    incomingHeaders.set("cookie", "__Secure-mo_at=token");
    incomingHeaders.set("x-request-id", "req-42");
    incomingHeaders.set("authorization", "Bearer should-not-forward");
    fetchMock.mockResolvedValue(jsonResponse({ status: "ok" }));

    await expect(serverFetch("/health/live", { schema: statusSchema })).resolves.toEqual({
      status: "ok",
    });

    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe("http://localhost:8000/health/live");
    expect(init?.method).toBe("GET");
    expect(init?.cache).toBe("no-store");
    expect(init?.headers).toEqual({
      accept: "application/json, application/problem+json",
      cookie: "__Secure-mo_at=token",
      "x-request-id": "req-42",
    });
  });

  it("sends JSON bodies", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ status: "ok" }));

    await serverFetch("/v1/things", {
      schema: statusSchema,
      method: "POST",
      body: { name: "x" },
      headers: { "idempotency-key": "key-1" },
    });

    const init = fetchMock.mock.calls[0]?.[1];
    expect(init?.body).toBe(JSON.stringify({ name: "x" }));
    expect(init?.headers).toMatchObject({
      "content-type": "application/json",
      "idempotency-key": "key-1",
    });
  });

  it("normalizes problem responses", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        { type: "about:blank", title: "Not found", status: 404, code: "not_found" },
        404,
        { "x-request-id": "req-7" },
      ),
    );

    await expect(serverFetch("/v1/missing", { schema: statusSchema })).rejects.toMatchObject({
      kind: "http",
      status: 404,
      code: "not_found",
      requestId: "req-7",
    });
  });

  it("normalizes empty and non-JSON error bodies", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 503 }));
    await expect(serverFetch("/v1/a", { schema: statusSchema })).rejects.toMatchObject({
      status: 503,
      title: "Service unavailable",
    });

    fetchMock.mockResolvedValueOnce(new Response("upstream down", { status: 502 }));
    await expect(serverFetch("/v1/b", { schema: statusSchema })).rejects.toMatchObject({
      status: 502,
      detail: null,
    });
  });

  it("rejects responses that do not match the schema", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ status: "broken" }));

    await expect(serverFetch("/v1/a", { schema: statusSchema })).rejects.toMatchObject({
      code: "invalid_response",
    });
  });

  it("normalizes network failures and timeouts", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("fetch failed"));
    await expect(serverFetch("/v1/a", { schema: statusSchema })).rejects.toMatchObject({
      kind: "network",
    });

    fetchMock.mockRejectedValueOnce(new DOMException("timed out", "TimeoutError"));
    const timeout = serverFetch("/v1/a", {
      schema: statusSchema,
      timeoutMs: 5,
      signal: new AbortController().signal,
    });
    await expect(timeout).rejects.toBeInstanceOf(ApiError);
    await expect(timeout).rejects.toMatchObject({ kind: "timeout" });
  });
});
