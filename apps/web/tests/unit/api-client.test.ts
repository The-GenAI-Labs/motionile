import { AxiosError, AxiosHeaders, type InternalAxiosRequestConfig } from "axios";
import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api/api-error";
import { apiClient, createApiClient } from "@/lib/api/client";
import { API_ACCEPT_HEADER, API_TIMEOUT_MS } from "@/lib/api/constants";

describe("api client", () => {
  it("targets the configured API with credentials, a timeout and JSON headers", () => {
    expect(apiClient.defaults.baseURL).toBe("http://localhost:8000");
    expect(apiClient.defaults.withCredentials).toBe(true);
    expect(apiClient.defaults.timeout).toBe(API_TIMEOUT_MS);
    expect(apiClient.defaults.headers["Accept"]).toBe(API_ACCEPT_HEADER);
  });

  it("returns successful responses untouched", async () => {
    const client = createApiClient("https://api.motionile.test");
    const response = await client.get("/v1/ping", {
      adapter: (config) =>
        Promise.resolve({
          data: { ok: true },
          status: 200,
          statusText: "OK",
          headers: new AxiosHeaders(),
          config,
        }),
    });

    expect(response.data).toEqual({ ok: true });
    expect(response.config.baseURL).toBe("https://api.motionile.test");
  });

  it("rejects with a normalized ApiError", async () => {
    const client = createApiClient("https://api.motionile.test");
    const request = client.get("/v1/jobs", {
      adapter: (config: InternalAxiosRequestConfig) =>
        Promise.reject(
          new AxiosError(
            "Request failed",
            "ERR_BAD_REQUEST",
            config,
            {},
            {
              status: 403,
              statusText: "Forbidden",
              data: { type: "about:blank", title: "Forbidden", status: 403, code: "forbidden" },
              headers: new AxiosHeaders({ "x-request-id": "req-1" }),
              config,
            },
          ),
        ),
    });

    await expect(request).rejects.toBeInstanceOf(ApiError);
    await expect(request).rejects.toMatchObject({
      status: 403,
      code: "forbidden",
      requestId: "req-1",
    });
  });
});
