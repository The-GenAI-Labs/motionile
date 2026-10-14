import { expect, test } from "@playwright/test";

import { ALLOWED_ORIGIN, clientHeaders, ECHO_PATH } from "./support.js";

const WEB_BASE_URL = process.env["WEB_BASE_URL"] ?? "http://localhost:3000";
const REQUEST_ID = /^[A-Za-z0-9._-]{8,64}$/;

function directives(policy: string): Map<string, string[]> {
  return new Map(
    policy
      .split(";")
      .map((part) => part.trim().split(/\s+/))
      .filter((tokens) => tokens[0])
      .map(([name, ...values]) => [name ?? "", values]),
  );
}

test.describe("API", () => {
  for (const path of ["/health/live", ECHO_PATH]) {
    test(`${path} carries the security headers`, async ({ request }) => {
      const response =
        path === ECHO_PATH
          ? await request.post(path, {
              headers: clientHeaders({ Origin: ALLOWED_ORIGIN }),
              data: { message: "hi" },
            })
          : await request.get(path);
      const headers = response.headers();

      expect(headers["x-content-type-options"]).toBe("nosniff");
      expect(headers["x-frame-options"]).toBe("DENY");
      expect(headers["referrer-policy"]).toBe("no-referrer");
      expect(headers["cross-origin-opener-policy"]).toBe("same-origin");
      expect(headers["cross-origin-resource-policy"]).toBe("same-site");
      expect(headers["permissions-policy"]).toContain("camera=()");
      expect(headers["cache-control"]).toBe("no-store");
      expect(headers["x-request-id"]).toMatch(REQUEST_ID);
      expect(headers["x-powered-by"]).toBeUndefined();
    });
  }

  test("errors carry the same headers", async ({ request }) => {
    const response = await request.get("/v1/does-not-exist", { headers: clientHeaders() });

    expect(response.status()).toBe(404);
    expect(response.headers()["x-content-type-options"]).toBe("nosniff");
    expect(response.headers()["content-type"]).toBe("application/problem+json");
  });

  test("a valid client request ID is echoed and an invalid one is replaced", async ({
    request,
  }) => {
    const echoed = await request.get("/health/live", {
      headers: { "X-Request-ID": "trace-0001-abcd" },
    });
    const replaced = await request.get("/health/live", { headers: { "X-Request-ID": "<script>" } });

    expect(echoed.headers()["x-request-id"]).toBe("trace-0001-abcd");
    expect(replaced.headers()["x-request-id"]).not.toBe("<script>");
    expect(replaced.headers()["x-request-id"]).toMatch(REQUEST_ID);
  });
});

test.describe("web app", () => {
  for (const path of ["/", "/pricing", "/does-not-exist"]) {
    test(`${path} carries the security headers and a strict CSP`, async ({ request }) => {
      const response = await request.get(`${WEB_BASE_URL}${path}`);
      const headers = response.headers();
      const policy = directives(headers["content-security-policy"] ?? "");

      expect(headers["x-content-type-options"]).toBe("nosniff");
      expect(headers["referrer-policy"]).toBe("strict-origin-when-cross-origin");
      expect(headers["strict-transport-security"]).toContain("max-age=");
      expect(headers["permissions-policy"]).toContain("camera=()");
      expect(headers["x-powered-by"]).toBeUndefined();
      expect(policy.get("default-src")).toEqual(["'self'"]);
      expect(policy.get("frame-ancestors")).toEqual(["'none'"]);
      expect(policy.get("object-src")).toEqual(["'none'"]);
      expect(policy.get("base-uri")).toEqual(["'self'"]);
      expect(policy.get("form-action")).toEqual(["'self'"]);
      expect(policy.get("script-src")).not.toContain("'unsafe-eval'");
      expect(policy.get("connect-src")).toContain("'self'");
    });
  }
});
