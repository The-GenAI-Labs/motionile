import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { loadSharedVideo } from "@/features/library/api/share.server.api";
import { ApiError } from "@/lib/api/api-error";

const { serverFetch } = vi.hoisted(() => ({ serverFetch: vi.fn() }));

vi.mock("@/lib/api/server", () => ({ serverFetch }));
vi.mock("react", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  cache: <Fn>(fn: Fn): Fn => fn,
}));

const SECRET = "share-internal-secret-0123456789abcdef";

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubEnv("SHARE_INTERNAL_SECRET", SECRET);
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe("loadSharedVideo", () => {
  it("fetches the public share endpoint without caching", async () => {
    serverFetch.mockResolvedValue({ title: "x" });

    await expect(loadSharedVideo("abc123abc123")).resolves.toEqual({ title: "x" });
    expect(serverFetch).toHaveBeenCalledWith(
      "/v1/share/abc123abc123",
      expect.objectContaining({ cache: "no-store" }),
    );
  });

  it("does not call the API for a slug with unexpected characters", async () => {
    await expect(loadSharedVideo("../admin")).resolves.toBeNull();
    expect(serverFetch).not.toHaveBeenCalled();
  });

  it("returns null when the link is missing or revoked", async () => {
    serverFetch.mockRejectedValue(
      new ApiError({
        kind: "http",
        status: 404,
        code: "share_not_found",
        title: "x",
        detail: null,
      }),
    );

    await expect(loadSharedVideo("abc123abc123")).resolves.toBeNull();
  });

  it("rethrows other failures", async () => {
    serverFetch.mockRejectedValue(
      new ApiError({ kind: "http", status: 429, code: "rate_limited", title: "x", detail: null }),
    );

    await expect(loadSharedVideo("abc123abc123")).rejects.toMatchObject({ status: 429 });
  });

  it("authenticates the server as the internal caller", async () => {
    serverFetch.mockResolvedValue({ title: "x" });

    await loadSharedVideo("abc123abc123");

    expect(serverFetch).toHaveBeenCalledWith(
      "/v1/share/abc123abc123",
      expect.objectContaining({ headers: { "X-Motionile-Internal": SECRET } }),
    );
  });

  it("refuses to call the API in production without the secret", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("SHARE_INTERNAL_SECRET", "");

    await expect(loadSharedVideo("abc123abc123")).rejects.toThrow("SHARE_INTERNAL_SECRET");
    expect(serverFetch).not.toHaveBeenCalled();
  });

  it("logs the problem and calls the API without the header outside production", async () => {
    const logged = vi.spyOn(process.stderr, "write").mockImplementation(() => true);
    vi.stubEnv("SHARE_INTERNAL_SECRET", "");
    serverFetch.mockResolvedValue({ title: "x" });

    await expect(loadSharedVideo("abc123abc123")).resolves.toEqual({ title: "x" });

    expect(logged).toHaveBeenCalledWith(expect.stringContaining("SHARE_INTERNAL_SECRET"));
    expect(serverFetch).toHaveBeenCalledWith(
      "/v1/share/abc123abc123",
      expect.objectContaining({ headers: {} }),
    );
  });

  it("does not need the secret for a slug it will not look up", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("SHARE_INTERNAL_SECRET", "");

    await expect(loadSharedVideo("../admin")).resolves.toBeNull();
  });
});
