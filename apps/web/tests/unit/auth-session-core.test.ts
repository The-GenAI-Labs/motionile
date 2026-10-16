import { AxiosError, AxiosHeaders, type InternalAxiosRequestConfig } from "axios";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient, createApiClient } from "@/lib/api/client";
import { readAccessExpiry } from "@/lib/auth/cookies";
import { refreshSession } from "@/lib/auth/refresh";
import { safeNextPath } from "@/lib/auth/routes";
import { expireSession } from "@/lib/auth/session-expiry";

vi.mock("@/lib/auth/session-expiry", () => ({ expireSession: vi.fn() }));

const response = (config: InternalAxiosRequestConfig, code?: string) => ({
  config,
  status: code ? 401 : 204,
  statusText: code ? "Unauthorized" : "No Content",
  headers: new AxiosHeaders(),
  data: code ? { code } : undefined,
});

const failure = (config: InternalAxiosRequestConfig, code: string) =>
  new AxiosError("Failed", "ERR_BAD_REQUEST", config, undefined, response(config, code));

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  document.cookie = "mo_auth=; Max-Age=0";
  document.cookie = "mo_csrf=; Max-Age=0";
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("safe return paths", () => {
  it.each([
    undefined,
    null,
    "",
    "https://evil.test",
    "//evil.test",
    "/\\evil.test",
    "/%2fevil.test",
    "/%255cevil.test",
    "/%0aevil.test",
    "/login",
    "/verify?next=/settings",
    "/a/../login",
    "/refresh/",
    "/javascript:alert(1)",
    "/%zz",
    "/ /evil.test",
  ])("rejects %s", (value) => {
    expect(safeNextPath(value)).toBe("/dashboard");
  });

  it.each(["/settings/security", "/library?cursor=abc#recent", "/admin/users"])(
    "preserves %s",
    (value) => {
      expect(safeNextPath(value)).toBe(value);
    },
  );

  it("reads only valid numeric expiry hints", () => {
    expect(readAccessExpiry()).toBeNull();
    document.cookie = "mo_auth=invalid";
    expect(readAccessExpiry()).toBeNull();
    document.cookie = "mo_auth=2000000000";
    expect(readAccessExpiry()).toBe(2000000000000);
  });
});

describe("session HTTP coordination", () => {
  it("copies the CSRF cookie on writes only", async () => {
    document.cookie = "mo_csrf=bound-token";
    const client = createApiClient();
    const headers: unknown[] = [];
    client.defaults.adapter = (config) => {
      headers.push(config.headers.get("X-CSRF-Token"));
      return Promise.resolve(response(config));
    };
    await client.get("/read");
    await client.post("/write");
    await client.delete("/delete");
    expect(headers).toEqual([undefined, "bound-token", "bound-token"]);
  });

  it("shares refresh for concurrent expired requests and retries each once", async () => {
    let release: (() => void) | undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const refresh = vi.spyOn(apiClient, "post").mockImplementation(async () => {
      await gate;
      return { data: undefined };
    });
    const client = createApiClient();
    const calls = new Map<string, number>();
    client.defaults.adapter = (config) => {
      const key = config.url ?? "";
      calls.set(key, (calls.get(key) ?? 0) + 1);
      return config.retried
        ? Promise.resolve(response(config))
        : Promise.reject(failure(config, "token_expired"));
    };
    const requests = Promise.all([client.get("/one"), client.get("/two")]);
    await vi.waitFor(() => {
      expect(refresh).toHaveBeenCalledTimes(1);
    });
    release?.();
    await requests;
    expect([...calls.values()]).toEqual([2, 2]);
  });

  it("fails a shared refresh once and never retries a failed request", async () => {
    const refresh = vi.spyOn(apiClient, "post").mockRejectedValue(new Error("Offline"));
    const client = createApiClient();
    client.defaults.adapter = (config) => Promise.reject(failure(config, "token_expired"));
    const results = await Promise.allSettled([client.get("/one"), client.get("/two")]);
    expect(results.every((result) => result.status === "rejected")).toBe(true);
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(expireSession).toHaveBeenCalledTimes(1);
  });

  it("never refreshes a refresh call", async () => {
    const refresh = vi.spyOn(apiClient, "post");
    const client = createApiClient();
    client.defaults.adapter = (config) => Promise.reject(failure(config, "token_expired"));
    await expect(
      client.post("/v1/auth/refresh", undefined, { skipAuthRefresh: true }),
    ).rejects.toMatchObject({ code: "token_expired" });
    expect(refresh).not.toHaveBeenCalled();
  });

  it("never retries an original request twice", async () => {
    const refresh = vi.spyOn(apiClient, "post").mockResolvedValue({ data: undefined });
    const client = createApiClient();
    const adapter = vi.fn((config: InternalAxiosRequestConfig) =>
      Promise.reject(failure(config, "token_expired")),
    );
    client.defaults.adapter = adapter;
    await expect(client.get("/one", { authenticated: true })).rejects.toMatchObject({
      code: "token_expired",
    });
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(adapter).toHaveBeenCalledTimes(2);
    expect(expireSession).toHaveBeenCalledTimes(1);
  });

  it("retries a conflict without refreshing", async () => {
    vi.useFakeTimers();
    const refresh = vi.spyOn(apiClient, "post");
    const client = createApiClient();
    client.defaults.adapter = (config) =>
      config.retried
        ? Promise.resolve(response(config))
        : Promise.reject(failure(config, "refresh_conflict"));
    const request = client.get("/one");
    await vi.advanceTimersByTimeAsync(250);
    await request;
    expect(refresh).not.toHaveBeenCalled();
  });

  it("does not expire anonymous requests", async () => {
    const client = createApiClient();
    client.defaults.adapter = (config) => Promise.reject(failure(config, "unauthenticated"));
    await expect(client.get("/login")).rejects.toMatchObject({ code: "unauthenticated" });
    expect(expireSession).not.toHaveBeenCalled();
    await expect(client.get("/me", { authenticated: true })).rejects.toMatchObject({
      code: "unauthenticated",
    });
    expect(expireSession).toHaveBeenCalledTimes(1);
  });

  it("rechecks shared generation under the lock even when expiry is unchanged", async () => {
    const refresh = vi.spyOn(apiClient, "post");
    const requestLock = vi.fn(async (_name: string, callback: () => Promise<void>) => {
      localStorage.setItem("mo-auth-refresh-generation", "other-tab-rotated");
      await callback();
    });
    vi.stubGlobal("navigator", { locks: { request: requestLock } });
    document.cookie = "mo_auth=2000000000";
    await refreshSession();
    expect(requestLock).toHaveBeenCalledWith("mo-auth-refresh", expect.any(Function));
    expect(refresh).not.toHaveBeenCalled();
  });
});
