import { expect, test } from "@playwright/test";

const VERSION_PATTERN = /\d+\.\d+/;

test("liveness responds with ok", async ({ request }) => {
  const response = await request.get("/health/live");

  expect(response.status()).toBe(200);
  expect(await response.json()).toEqual({ status: "ok" });
});

test("readiness reports every dependency", async ({ request }) => {
  const response = await request.get("/health/ready");

  expect(response.status()).toBe(200);
  expect(await response.json()).toEqual({ status: "ok", checks: { postgres: "ok", redis: "ok" } });
});

test("responses do not reveal server software versions", async ({ request }) => {
  const response = await request.get("/health/live");
  const headers = response.headers();

  expect(headers["server"] ?? "").not.toMatch(VERSION_PATTERN);
  expect(headers["server"] ?? "").not.toMatch(/uvicorn/i);
  expect(headers["x-powered-by"]).toBeUndefined();
});
