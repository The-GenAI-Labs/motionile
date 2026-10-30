import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api/api-error";

const respond = (body: unknown) =>
  ApiError.fromResponse({ status: 409, body, getHeader: () => null });

describe("ApiError extensions", () => {
  it("keeps problem members beyond the standard ones", () => {
    const error = respond({
      type: "urn:motionile:problem:activation_blocked",
      title: "The version cannot be activated yet",
      status: 409,
      code: "activation_blocked",
      missingSuites: "safety,cost",
      failedSuites: "",
      limit: 2,
      retryable: true,
    });

    expect(error.extensions).toEqual({
      missingSuites: "safety,cost",
      failedSuites: "",
      limit: 2,
      retryable: true,
    });
  });

  it("ignores nested values and standard members", () => {
    const error = respond({
      type: "urn:motionile:problem:x",
      title: "t",
      status: 409,
      code: "x",
      requestId: "r1",
      nested: { a: 1 },
    });

    expect(error.extensions).toEqual({});
  });

  it("is empty for network failures and loose bodies", () => {
    expect(ApiError.ofKind("network").extensions).toEqual({});
    expect(respond({ message: "nope" }).extensions).toEqual({});
  });
});
