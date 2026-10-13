import { describe, expect, it } from "vitest";

import { dynamic, GET } from "@/app/api/health/route";

describe("health route", () => {
  it("reports ok without caching", async () => {
    const response = GET();

    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(await response.json()).toEqual({ status: "ok" });
  });

  it("is always rendered dynamically", () => {
    expect(dynamic).toBe("force-dynamic");
  });
});
