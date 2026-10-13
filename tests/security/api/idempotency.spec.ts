import { expect, test } from "@playwright/test";

import {
  clientHeaders,
  IDEMPOTENT_PATH,
  type Problem,
  PROBLEM_JSON,
  uniqueKey,
} from "./support.js";

interface Item {
  id: string;
  itemName: string;
}

test("a repeated request replays the first response", async ({ request }) => {
  const headers = clientHeaders({ "Idempotency-Key": uniqueKey("replay") });

  const first = await request.post(IDEMPOTENT_PATH, { headers, data: { itemName: "widget" } });
  const second = await request.post(IDEMPOTENT_PATH, { headers, data: { itemName: "widget" } });

  expect(first.status()).toBe(201);
  expect(first.headers()["idempotent-replayed"]).toBeUndefined();
  expect(second.status()).toBe(201);
  expect(second.headers()["idempotent-replayed"]).toBe("true");
  expect((await second.json()) as Item).toEqual((await first.json()) as Item);
  expect(second.headers()["location"]).toBe(first.headers()["location"]);
});

test("reusing a key with a different body is a conflict", async ({ request }) => {
  const headers = clientHeaders({ "Idempotency-Key": uniqueKey("reuse") });

  await request.post(IDEMPOTENT_PATH, { headers, data: { itemName: "widget" } });
  const reused = await request.post(IDEMPOTENT_PATH, { headers, data: { itemName: "gadget" } });
  const problem = (await reused.json()) as Problem;

  expect(reused.status()).toBe(409);
  expect(reused.headers()["content-type"]).toBe(PROBLEM_JSON);
  expect(problem.code).toBe("idempotency_key_reused");
});

test("the key is required and validated", async ({ request }) => {
  const missing = await request.post(IDEMPOTENT_PATH, {
    headers: clientHeaders(),
    data: { itemName: "widget" },
  });
  const invalid = await request.post(IDEMPOTENT_PATH, {
    headers: clientHeaders({ "Idempotency-Key": "has spaces in it" }),
    data: { itemName: "widget" },
  });

  expect(missing.status()).toBe(400);
  expect(((await missing.json()) as Problem).code).toBe("idempotency_key_required");
  expect(invalid.status()).toBe(400);
  expect(((await invalid.json()) as Problem).code).toBe("idempotency_key_invalid");
});

test("concurrent duplicates create exactly one item", async ({ request }) => {
  const headers = clientHeaders({ "Idempotency-Key": uniqueKey("concurrent") });

  const responses = await Promise.all(
    Array.from({ length: 8 }, () =>
      request.post(IDEMPOTENT_PATH, { headers, data: { itemName: "widget" } }),
    ),
  );

  const created = responses.filter((response) => response.status() === 201);
  const originals = created.filter(
    (response) => response.headers()["idempotent-replayed"] === undefined,
  );
  const conflicts = responses.filter((response) => response.status() === 409);
  const ids = new Set(
    await Promise.all(created.map(async (response) => ((await response.json()) as Item).id)),
  );

  expect(originals).toHaveLength(1);
  expect(created.length + conflicts.length).toBe(responses.length);
  expect(ids.size).toBe(1);
  for (const conflict of conflicts) {
    expect(((await conflict.json()) as Problem).code).toBe("idempotency_request_in_progress");
    expect(conflict.headers()["retry-after"]).toBeDefined();
  }
});
