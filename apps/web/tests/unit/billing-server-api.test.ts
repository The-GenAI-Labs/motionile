import { afterEach, describe, expect, it, vi } from "vitest";

import { billingProducts, loadPricingProducts } from "@/features/billing/api/billing.server.api";

import { products } from "./billing-fixtures";

const jsonResponse = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status }));

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("billing products on the server", () => {
  it("fetches the public listing tagged for revalidation", async () => {
    const fetchMock = vi.fn(() => jsonResponse(products));
    vi.stubGlobal("fetch", fetchMock);

    await expect(billingProducts()).resolves.toEqual(products);

    const [url, init] = fetchMock.mock.calls[0] as unknown as [URL, RequestInit & { next: object }];
    expect(url.toString()).toBe("http://localhost:8000/v1/billing/products");
    expect(init.next).toEqual({ revalidate: 300, tags: ["billing-products"] });
  });

  it("rejects an unsuccessful response and an unexpected shape", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => jsonResponse({ error: "down" }, 503)),
    );
    await expect(billingProducts()).rejects.toThrow(/status 503/);

    vi.stubGlobal(
      "fetch",
      vi.fn(() => jsonResponse({ creditPacks: "nope" })),
    );
    await expect(billingProducts()).rejects.toThrow();
  });
});

describe("pricing page outage handling", () => {
  it("renders without products while building and keeps rendering in development", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("fetch failed"))),
    );

    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("NEXT_PHASE", "phase-production-build");
    await expect(loadPricingProducts()).resolves.toBeNull();

    vi.stubEnv("NEXT_PHASE", "");
    vi.stubEnv("NODE_ENV", "development");
    await expect(loadPricingProducts()).resolves.toBeNull();
  });

  it("fails a production revalidation so the last good page is kept", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("fetch failed"))),
    );
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("NEXT_PHASE", "phase-production-server");

    await expect(loadPricingProducts()).rejects.toThrow("fetch failed");
  });

  it("returns the products when the API is up", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => jsonResponse(products)),
    );
    vi.stubEnv("NODE_ENV", "production");

    await expect(loadPricingProducts()).resolves.toEqual(products);
  });
});
