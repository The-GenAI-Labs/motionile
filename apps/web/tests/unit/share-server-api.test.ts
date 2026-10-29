import { beforeEach, describe, expect, it, vi } from "vitest";

import { loadSharedVideo } from "@/features/library/api/share.server.api";
import { ApiError } from "@/lib/api/api-error";

const { serverFetch } = vi.hoisted(() => ({ serverFetch: vi.fn() }));

vi.mock("@/lib/api/server", () => ({ serverFetch }));
vi.mock("react", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  cache: <Fn>(fn: Fn): Fn => fn,
}));

beforeEach(() => {
  vi.clearAllMocks();
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
});
