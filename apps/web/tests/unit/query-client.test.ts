import { environmentManager, QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/api-error";
import {
  DEFAULT_STALE_TIME_MS,
  getQueryClient,
  makeQueryClient,
  MAX_QUERY_RETRIES,
  retryDelay,
  shouldRetryQuery,
} from "@/lib/query/query-client";
import { getServerQueryClient } from "@/lib/query/server-query-client";

const httpError = (status: number, retryAfterSeconds: number | null = null) =>
  new ApiError({
    kind: "http",
    status,
    code: "x",
    title: "x",
    detail: null,
    retryAfterSeconds,
  });

afterEach(() => {
  vi.useRealTimers();
  environmentManager.setIsServer(() => typeof window === "undefined");
});

describe("query retry rules", () => {
  it.each([400, 401, 403, 404, 409, 422, 429])("never retries a %s response", (status) => {
    expect(shouldRetryQuery(0, httpError(status))).toBe(false);
  });

  it.each([
    ["a 500 response", httpError(500)],
    ["a 503 response", httpError(503)],
    ["a network error", ApiError.ofKind("network")],
    ["a timeout", ApiError.ofKind("timeout")],
    ["a raw fetch failure", new TypeError("fetch failed")],
  ])("retries %s at most twice", (_label, error) => {
    expect(shouldRetryQuery(0, error)).toBe(true);
    expect(shouldRetryQuery(1, error)).toBe(true);
    expect(shouldRetryQuery(MAX_QUERY_RETRIES, error)).toBe(false);
  });

  it("never retries cancelled or unknown errors", () => {
    expect(shouldRetryQuery(0, ApiError.ofKind("cancelled"))).toBe(false);
    expect(shouldRetryQuery(0, new Error("bug"))).toBe(false);
  });

  it("backs off exponentially with a cap", () => {
    expect(retryDelay(0)).toBe(1_000);
    expect(retryDelay(1)).toBe(2_000);
    expect(retryDelay(2)).toBe(4_000);
    expect(retryDelay(10)).toBe(10_000);
  });

  it("honours retry-after within the cap", () => {
    expect(retryDelay(0, httpError(503, 3))).toBe(3_000);
    expect(retryDelay(2, httpError(503, 1))).toBe(4_000);
    expect(retryDelay(0, httpError(503, 120))).toBe(10_000);
    expect(retryDelay(1, ApiError.ofKind("network"))).toBe(2_000);
  });

  it("retries a transient failure twice with backoff and then gives up", async () => {
    vi.useFakeTimers();
    const client = makeQueryClient();
    const queryFn = vi.fn(() => Promise.reject(ApiError.ofKind("network")));

    const result = client.query({ queryKey: ["flaky"], queryFn });
    const assertion = expect(result).rejects.toMatchObject({ kind: "network" });
    await vi.runAllTimersAsync();
    await assertion;

    expect(queryFn).toHaveBeenCalledTimes(3);
  });

  it("does not retry a client error", async () => {
    const client = makeQueryClient();
    const queryFn = vi.fn(() => Promise.reject(httpError(404)));

    await expect(client.query({ queryKey: ["missing"], queryFn })).rejects.toMatchObject({
      status: 404,
    });
    expect(queryFn).toHaveBeenCalledTimes(1);
  });
});

describe("query client defaults", () => {
  it("disables refetch on focus, sets a stale time and never retries mutations", () => {
    const defaults = makeQueryClient().getDefaultOptions();

    expect(defaults.queries?.refetchOnWindowFocus).toBe(false);
    expect(defaults.queries?.staleTime).toBe(DEFAULT_STALE_TIME_MS);
    expect(defaults.mutations?.retry).toBe(false);
  });

  it("dehydrates pending queries for streaming hydration", async () => {
    const client = makeQueryClient();
    const shouldDehydrate = client.getDefaultOptions().dehydrate?.shouldDehydrateQuery;
    void client.query({ queryKey: ["slow"], queryFn: () => new Promise(() => undefined) });
    await client.query({ queryKey: ["done"], queryFn: () => Promise.resolve(1) });

    const slow = client.getQueryCache().find({ queryKey: ["slow"] });
    const done = client.getQueryCache().find({ queryKey: ["done"] });
    expect(slow && shouldDehydrate?.(slow)).toBe(true);
    expect(done && shouldDehydrate?.(done)).toBe(true);
  });

  it("reuses one client in the browser", () => {
    const first = getQueryClient();

    expect(first).toBeInstanceOf(QueryClient);
    expect(getQueryClient()).toBe(first);
  });

  it("creates a fresh client per request on the server", () => {
    environmentManager.setIsServer(() => true);

    expect(getQueryClient()).not.toBe(getQueryClient());
    expect(getServerQueryClient()).toBeInstanceOf(QueryClient);
  });
});
