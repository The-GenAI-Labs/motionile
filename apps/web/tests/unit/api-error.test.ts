import { AxiosError, AxiosHeaders, CanceledError, type InternalAxiosRequestConfig } from "axios";
import { describe, expect, it } from "vitest";

import { API_ERROR_CODES, ApiError, isApiError } from "@/lib/api/api-error";

const requestConfig = { headers: new AxiosHeaders() } as InternalAxiosRequestConfig;

const axiosResponseError = (
  status: number,
  data: unknown,
  headers: Record<string, string> = {},
): AxiosError =>
  new AxiosError(
    `Request failed with status code ${status}`,
    "ERR_BAD_RESPONSE",
    requestConfig,
    {},
    {
      status,
      statusText: "",
      data,
      headers: new AxiosHeaders(headers),
      config: requestConfig,
    },
  );

describe("ApiError.from", () => {
  it("normalizes a problem+json response with field errors", () => {
    const error = ApiError.from(
      axiosResponseError(
        422,
        {
          type: "https://motionile.com/problems/validation",
          title: "Validation failed",
          status: 422,
          detail: "Check the highlighted fields.",
          instance: "/v1/jobs",
          code: "validation_failed",
          requestId: "req-body",
          errors: [{ field: "topic", message: "Topic is required", type: "missing" }],
        },
        { "x-request-id": "req-header" },
      ),
    );

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      kind: "http",
      status: 422,
      code: "validation_failed",
      title: "Validation failed",
      detail: "Check the highlighted fields.",
      type: "https://motionile.com/problems/validation",
      instance: "/v1/jobs",
      requestId: "req-body",
      message: "Check the highlighted fields.",
    });
    expect(error.fieldErrors).toEqual([
      { field: "topic", message: "Topic is required", type: "missing" },
    ]);
    expect(error.fieldError("topic")).toBe("Topic is required");
    expect(error.fieldError("other")).toBeUndefined();
    expect(error.isClientError).toBe(true);
    expect(error.isTransient).toBe(false);
  });

  it("falls back to the request id header and reads retry-after seconds", () => {
    const error = ApiError.from(
      axiosResponseError(
        429,
        { type: "about:blank", title: "Too many requests", status: 429, code: "rate_limited" },
        { "x-request-id": "req-123", "retry-after": "30" },
      ),
    );

    expect(error.requestId).toBe("req-123");
    expect(error.retryAfterSeconds).toBe(30);
    expect(error.detail).toBeNull();
    expect(error.message).toBe("Too many requests");
  });

  it("parses an HTTP date in retry-after", () => {
    const later = new Date(Date.now() + 5_000).toUTCString();
    const error = ApiError.from(axiosResponseError(503, "", { "retry-after": later }));

    expect(error.retryAfterSeconds).toBeGreaterThanOrEqual(3);
    expect(error.retryAfterSeconds).toBeLessThanOrEqual(6);
  });

  it("ignores an unparseable retry-after header", () => {
    expect(
      ApiError.from(axiosResponseError(503, "", { "retry-after": "soon" })).retryAfterSeconds,
    ).toBeNull();
  });

  it("normalizes a plain JSON error body", () => {
    const error = ApiError.from(axiosResponseError(400, { message: "Bad topic" }));

    expect(error).toMatchObject({
      kind: "http",
      status: 400,
      code: API_ERROR_CODES.http,
      title: "Bad request",
      detail: "Bad topic",
      type: "about:blank",
    });
  });

  it("keeps a code and title from a loose JSON body", () => {
    const error = ApiError.from(
      axiosResponseError(409, { code: "duplicate", title: "Already exists", error: "Duplicate" }),
    );

    expect(error).toMatchObject({
      code: "duplicate",
      title: "Already exists",
      detail: "Duplicate",
    });
  });

  it("parses a problem document sent as a JSON string", () => {
    const error = ApiError.from(
      axiosResponseError(
        404,
        JSON.stringify({
          type: "about:blank",
          title: "Not found",
          status: 404,
          code: "job_not_found",
        }),
      ),
    );

    expect(error.code).toBe("job_not_found");
  });

  it("normalizes a non-JSON body", () => {
    const error = ApiError.from(axiosResponseError(502, "<html>Bad gateway</html>"));

    expect(error).toMatchObject({
      kind: "http",
      status: 502,
      code: API_ERROR_CODES.http,
      title: "Bad gateway",
      detail: null,
    });
    expect(error.isServerError).toBe(true);
    expect(error.isTransient).toBe(true);
  });

  it("uses generic titles for unknown statuses", () => {
    expect(ApiError.from(axiosResponseError(599, null)).title).toBe("Server error");
    expect(ApiError.from(axiosResponseError(418, null)).title).toBe("Request failed");
  });

  it("normalizes a network error", () => {
    const error = ApiError.from(
      new AxiosError("Network Error", AxiosError.ERR_NETWORK, requestConfig, {}),
    );

    expect(error).toMatchObject({ kind: "network", status: null, code: "network_error" });
    expect(error.isTransient).toBe(true);
    expect(error.isClientError).toBe(false);
  });

  it.each(["ECONNABORTED", "ETIMEDOUT"])("normalizes a %s timeout", (code) => {
    const error = ApiError.from(new AxiosError("timeout", code, requestConfig, {}));

    expect(error).toMatchObject({ kind: "timeout", code: "request_timeout" });
    expect(error.isTransient).toBe(true);
  });

  it("normalizes axios cancellation", () => {
    expect(ApiError.from(new CanceledError()).kind).toBe("cancelled");
    expect(
      ApiError.from(new AxiosError("canceled", AxiosError.ERR_CANCELED, requestConfig)).kind,
    ).toBe("cancelled");
  });

  it("normalizes fetch abort, timeout and network failures", () => {
    expect(ApiError.from(new DOMException("aborted", "AbortError")).kind).toBe("cancelled");
    expect(ApiError.from(new DOMException("timed out", "TimeoutError")).kind).toBe("timeout");
    expect(ApiError.from(new DOMException("other", "NetworkError")).kind).toBe("network");
    expect(ApiError.from(new TypeError("fetch failed")).kind).toBe("network");
  });

  it("normalizes unknown thrown values", () => {
    for (const value of [new Error("boom"), "boom", 42, null, undefined, { reason: "x" }]) {
      const error = ApiError.from(value);
      expect(error).toMatchObject({ kind: "unknown", code: "unknown_error", status: null });
      expect(error.cause).toBe(value);
    }
  });

  it("returns an existing ApiError unchanged", () => {
    const original = ApiError.ofKind("network");

    expect(ApiError.from(original)).toBe(original);
    expect(isApiError(original)).toBe(true);
    expect(isApiError(new Error("x"))).toBe(false);
  });
});

describe("ApiError.fromResponse", () => {
  it("normalizes fetch style responses", () => {
    const headers = new Headers({ "x-request-id": "req-9" });
    const error = ApiError.fromResponse({
      status: 500,
      body: null,
      getHeader: (name) => headers.get(name),
    });

    expect(error).toMatchObject({
      status: 500,
      title: "Internal server error",
      requestId: "req-9",
      retryAfterSeconds: null,
    });
  });
});
