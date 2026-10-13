import { expect, test } from "@playwright/test";

import {
  ALLOWED_ORIGIN,
  clientHeaders,
  ECHO_PATH,
  FOREIGN_ORIGIN,
  type Problem,
  PROBLEM_JSON,
} from "./support.js";

const BODY = { message: "hello" };

test("state-changing requests from the web origin pass", async ({ request }) => {
  const response = await request.post(ECHO_PATH, {
    headers: clientHeaders({ Origin: ALLOWED_ORIGIN }),
    data: BODY,
  });

  expect(response.status()).toBe(200);
  expect(await response.json()).toMatchObject({ message: "hello", repeatCount: 1 });
});

for (const [label, headers] of [
  ["foreign Origin", { Origin: FOREIGN_ORIGIN }],
  ["null Origin", { Origin: "null" }],
  ["foreign Referer without Origin", { Referer: `${FOREIGN_ORIGIN}/attack.html` }],
] as const) {
  test(`state-changing requests with a ${label} are rejected`, async ({ request }) => {
    const response = await request.post(ECHO_PATH, { headers: clientHeaders(headers), data: BODY });
    const problem = (await response.json()) as Problem;

    expect(response.status()).toBe(403);
    expect(response.headers()["content-type"]).toBe(PROBLEM_JSON);
    expect(problem.code).toBe("origin_not_allowed");
    expect(problem.type).toBe("urn:motionile:problem:origin_not_allowed");
    expect(problem.requestId).toBe(response.headers()["x-request-id"]);
  });
}

test("safe methods are not blocked by the Origin guard", async ({ request }) => {
  const response = await request.get("/health/live", { headers: { Origin: FOREIGN_ORIGIN } });

  expect(response.status()).toBe(200);
});

test("webhook paths are exempt from the Origin guard", async ({ request }) => {
  const response = await request.post("/v1/webhooks/unknown", {
    headers: clientHeaders({ Origin: FOREIGN_ORIGIN }),
    data: {},
  });

  expect(response.status()).toBe(404);
});
