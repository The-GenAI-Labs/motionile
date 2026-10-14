import { describe, expect, it } from "vitest";

import {
  type ProblemDetails,
  type ReadinessResponse,
  zHealthLiveResponse,
  zHealthReadyResponse,
  zProblemDetails,
} from "../src/index";

describe("generated API contract", () => {
  it("accepts a live response", () => {
    expect(zHealthLiveResponse.parse({ status: "ok" })).toEqual({ status: "ok" });
  });

  it("rejects an unexpected liveness status", () => {
    expect(zHealthLiveResponse.safeParse({ status: "down" }).success).toBe(false);
  });

  it("describes readiness per dependency", () => {
    const response: ReadinessResponse = {
      status: "unavailable",
      checks: { postgres: "ok", redis: "unavailable" },
    };

    expect(zHealthReadyResponse.parse(response)).toEqual(response);
    expect(
      zHealthReadyResponse.safeParse({ status: "ok", checks: { postgres: "maybe", redis: "ok" } })
        .success,
    ).toBe(false);
  });

  it("parses problem details with field errors", () => {
    const problem: ProblemDetails = {
      type: "urn:motionile:problem:validation_failed",
      title: "Validation failed",
      status: 422,
      code: "validation_failed",
      requestId: "0192f0c0a1b27c3d8e9f0a1b2c3d4e5f",
      errors: [{ field: "body.email", message: "Field required", type: "missing" }],
    };

    expect(zProblemDetails.parse(problem)).toEqual(problem);
    expect(zProblemDetails.safeParse({ title: "x", status: 400 }).success).toBe(false);
  });
});
