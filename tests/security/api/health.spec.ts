import { expect, test } from "@playwright/test";

const VERSION_PATTERN = /\d+\.\d+/;

for (const path of ["/health/live", "/health/ready"]) {
  test(`${path} responds with ok`, async ({ request }) => {
    const response = await request.get(path);

    expect(response.status()).toBe(200);
    expect(await response.json()).toEqual({ status: "ok" });
  });
}

test("responses do not reveal server software versions", async ({ request }) => {
  const response = await request.get("/health/live");
  const headers = response.headers();

  expect(headers["server"] ?? "").not.toMatch(VERSION_PATTERN);
  expect(headers["server"] ?? "").not.toMatch(/uvicorn/i);
  expect(headers["x-powered-by"]).toBeUndefined();
});

test("responses carry baseline security headers", async ({ request }) => {
  const headers = (await request.get("/health/live")).headers();

  expect(headers["x-content-type-options"]).toBe("nosniff");
  expect(headers["x-frame-options"]).toBe("DENY");
});

test("unknown origins are not granted cross-origin access", async ({ request }) => {
  const response = await request.get("/health/live", {
    headers: { Origin: "https://evil.example" },
  });

  expect(response.headers()["access-control-allow-origin"]).toBeUndefined();
});
