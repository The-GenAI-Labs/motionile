import { describe, expect, it } from "vitest";

import { type HealthResponse, zGetLivenessResponse, zHealthResponse } from "../src/index";

describe("generated API contract", () => {
  it("accepts a healthy response", () => {
    const response: HealthResponse = { status: "ok" };

    expect(zHealthResponse.parse(response)).toEqual(response);
  });

  it("rejects an unexpected status", () => {
    expect(zGetLivenessResponse.safeParse({ status: "down" }).success).toBe(false);
  });
});
