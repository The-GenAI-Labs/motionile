import { beforeEach, describe, expect, it, vi } from "vitest";

import { recordShareView } from "@/features/library/api/library.api";

const { client } = vi.hoisted(() => ({ client: { get: vi.fn(), post: vi.fn() } }));

vi.mock("@/lib/api/client", () => ({ apiClient: client }));

beforeEach(() => {
  vi.clearAllMocks();
});

describe("recordShareView", () => {
  it("posts to the public view counter without a body or a session refresh", async () => {
    client.post.mockResolvedValue({ data: undefined, status: 204 });

    await expect(recordShareView("abc123abc123")).resolves.toBeUndefined();

    expect(client.post).toHaveBeenCalledWith("/v1/share/abc123abc123/views", undefined, {
      skipAuthRefresh: true,
    });
  });

  it("refuses a slug that could change the path", async () => {
    await expect(recordShareView("../jobs")).rejects.toThrow();

    expect(client.post).not.toHaveBeenCalled();
  });

  it("surfaces a failed request to the caller", async () => {
    client.post.mockRejectedValue(new Error("offline"));

    await expect(recordShareView("abc123abc123")).rejects.toThrow("offline");
  });
});
