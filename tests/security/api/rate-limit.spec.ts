import { expect, test } from "@playwright/test";

import {
  clientHeaders,
  type Problem,
  PROBLEM_JSON,
  RATE_LIMITED_PATH,
  uniqueClientIp,
} from "./support.js";

const LIMIT = 3;

test("the test policy allows three requests and then returns 429", async ({ request }) => {
  const headers = { "X-Forwarded-For": uniqueClientIp() };
  const statuses: number[] = [];
  const remaining: string[] = [];

  for (let attempt = 0; attempt < LIMIT; attempt += 1) {
    const response = await request.get(RATE_LIMITED_PATH, { headers });
    statuses.push(response.status());
    remaining.push(response.headers()["ratelimit-remaining"] ?? "");
  }
  const limited = await request.get(RATE_LIMITED_PATH, { headers });
  const problem = (await limited.json()) as Problem;

  expect(statuses).toEqual([200, 200, 200]);
  expect(remaining).toEqual(["2", "1", "0"]);
  expect(limited.status()).toBe(429);
  expect(limited.headers()["content-type"]).toBe(PROBLEM_JSON);
  expect(limited.headers()["ratelimit-limit"]).toBe(String(LIMIT));
  expect(Number(limited.headers()["retry-after"])).toBeGreaterThanOrEqual(1);
  expect(Number(limited.headers()["retry-after"])).toBeLessThanOrEqual(10);
  expect(problem.code).toBe("rate_limited");
});

test("limits are tracked per client", async ({ request }) => {
  const exhausted = { "X-Forwarded-For": uniqueClientIp() };
  for (let attempt = 0; attempt <= LIMIT; attempt += 1) {
    await request.get(RATE_LIMITED_PATH, { headers: exhausted });
  }

  const other = await request.get(RATE_LIMITED_PATH, { headers: clientHeaders() });

  expect(other.status()).toBe(200);
});

test("concurrent bursts never exceed the limit", async ({ request }) => {
  const headers = clientHeaders();

  const responses = await Promise.all(
    Array.from({ length: 12 }, () => request.get(RATE_LIMITED_PATH, { headers })),
  );

  expect(responses.filter((response) => response.status() === 200)).toHaveLength(LIMIT);
  expect(responses.filter((response) => response.status() === 429)).toHaveLength(12 - LIMIT);
});

test("the window slides and capacity returns", async ({ request }) => {
  test.slow();
  const headers = clientHeaders();
  for (let attempt = 0; attempt <= LIMIT; attempt += 1) {
    await request.get(RATE_LIMITED_PATH, { headers });
  }
  const limited = await request.get(RATE_LIMITED_PATH, { headers });
  const waitSeconds = Number(limited.headers()["retry-after"] ?? "10");

  await new Promise((resolve) => setTimeout(resolve, (waitSeconds + 1) * 1000));
  const recovered = await request.get(RATE_LIMITED_PATH, { headers });

  expect(limited.status()).toBe(429);
  expect(recovered.status()).toBe(200);
});
