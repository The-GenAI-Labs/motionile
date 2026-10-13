import { expect, test } from "@playwright/test";

import { ALLOWED_ORIGIN, clientHeaders, ECHO_PATH, FOREIGN_ORIGIN } from "./support.js";

const PREFLIGHT = {
  "Access-Control-Request-Method": "POST",
  "Access-Control-Request-Headers": "content-type,idempotency-key",
};

test("preflight from the web origin is allowed with credentials", async ({ request }) => {
  const response = await request.fetch(ECHO_PATH, {
    method: "OPTIONS",
    headers: { Origin: ALLOWED_ORIGIN, ...PREFLIGHT },
  });
  const headers = response.headers();

  expect(response.status()).toBe(200);
  expect(headers["access-control-allow-origin"]).toBe(ALLOWED_ORIGIN);
  expect(headers["access-control-allow-credentials"]).toBe("true");
  expect(headers["access-control-allow-methods"]).toContain("POST");
  expect(headers["access-control-allow-headers"]?.toLowerCase()).toContain("idempotency-key");
  expect(headers["vary"]?.toLowerCase()).toContain("origin");
});

test("preflight from a foreign origin is refused", async ({ request }) => {
  const response = await request.fetch(ECHO_PATH, {
    method: "OPTIONS",
    headers: { Origin: FOREIGN_ORIGIN, ...PREFLIGHT },
  });

  expect(response.status()).toBe(400);
  expect(response.headers()["access-control-allow-origin"]).toBeUndefined();
});

test("simple requests expose only allowed origins and the documented headers", async ({
  request,
}) => {
  const allowed = await request.get("/health/live", { headers: { Origin: ALLOWED_ORIGIN } });
  const foreign = await request.get("/health/live", { headers: { Origin: FOREIGN_ORIGIN } });

  expect(allowed.headers()["access-control-allow-origin"]).toBe(ALLOWED_ORIGIN);
  expect(allowed.headers()["access-control-expose-headers"]?.toLowerCase()).toContain(
    "x-request-id",
  );
  expect(foreign.headers()["access-control-allow-origin"]).toBeUndefined();
});

test("wildcards and lookalike origins are never reflected", async ({ request }) => {
  for (const origin of [
    "null",
    `${ALLOWED_ORIGIN}.evil.example`,
    ALLOWED_ORIGIN.replace("http", "https"),
  ]) {
    const response = await request.post(ECHO_PATH, {
      headers: clientHeaders({ Origin: origin }),
      data: { message: "hi" },
    });

    expect(response.headers()["access-control-allow-origin"]).toBeUndefined();
    expect(response.headers()["access-control-allow-origin"]).not.toBe("*");
  }
});
