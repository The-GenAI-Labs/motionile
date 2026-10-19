import { beforeEach, describe, expect, it, vi } from "vitest";

import { POST } from "@/app/api/revalidate/route";
import { BILLING_PRODUCTS_TAG, isRevalidatableTag } from "@/lib/revalidation/tags";

const { revalidateTag } = vi.hoisted(() => ({
  revalidateTag: vi.fn<(tag: string, profile: string) => void>(),
}));

vi.mock("next/cache", () => ({ revalidateTag }));
vi.mock("@/config/server-env", () => ({
  serverEnv: { apiBaseUrl: "http://localhost:8000", catalogRevalidationSecret: "s".repeat(32) },
}));

const SECRET = "s".repeat(32);

const post = (body: unknown, authorization: string | null = `Bearer ${SECRET}`) =>
  POST(
    new Request("https://motionile.test/api/revalidate", {
      method: "POST",
      headers: authorization === null ? {} : { authorization },
      body: typeof body === "string" ? body : JSON.stringify(body),
    }),
  );

beforeEach(() => {
  revalidateTag.mockClear();
});

describe("revalidate route", () => {
  it("revalidates the billing products tag", async () => {
    const response = await post({ tags: [BILLING_PRODUCTS_TAG] });

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ revalidated: ["billing-products"] });
    expect(revalidateTag).toHaveBeenCalledExactlyOnceWith("billing-products", "max");
  });

  it("still revalidates catalog tags, once each", async () => {
    const response = await post({
      tags: ["catalog", "catalog:education", "catalog:education", "catalog:category:tech/web"],
    });

    expect(response.status).toBe(200);
    expect(revalidateTag.mock.calls.map(([tag]) => tag)).toEqual([
      "catalog",
      "catalog:education",
      "catalog:category:tech/web",
    ]);
  });

  it("refuses every tag when one is not allowed", async () => {
    const response = await post({ tags: ["billing-products", "everything"] });

    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({ error: "Unsupported tag" });
    expect(revalidateTag).not.toHaveBeenCalled();
  });

  it("rejects a missing or wrong secret", async () => {
    expect((await post({ tags: ["catalog"] }, null)).status).toBe(401);
    expect((await post({ tags: ["catalog"] }, "Bearer wrong")).status).toBe(401);
    expect(revalidateTag).not.toHaveBeenCalled();
  });

  it("rejects malformed bodies", async () => {
    expect((await post("not json")).status).toBe(400);
    expect((await post({ tags: [] })).status).toBe(400);
    expect((await post({ tags: [""] })).status).toBe(400);
  });
});

describe("revalidatable tags", () => {
  it.each(["billing-products", "catalog", "catalog:abc", "catalog:category:a/b"])(
    "allows %s",
    (tag) => {
      expect(isRevalidatableTag(tag)).toBe(true);
    },
  );

  it.each(["", "billing", "billing-products:x", "catalogue", "catalog:", "catalog: x", "all"])(
    "rejects %j",
    (tag) => {
      expect(isRevalidatableTag(tag)).toBe(false);
    },
  );
});
