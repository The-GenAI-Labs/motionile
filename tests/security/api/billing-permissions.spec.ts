import { randomUUID } from "node:crypto";

import { expect, test } from "@playwright/test";

import { signupWithRole } from "../../support/admin.js";
import { BillingSession } from "../../support/billing.js";
import { PROBLEM_JSON } from "./support.js";

type Endpoint = readonly [method: string, path: string, body?: Record<string, unknown>];

const missingId = randomUUID();

const READ_ENDPOINTS: Endpoint[] = [
  ["GET", "/v1/admin/billing/products"],
  ["GET", `/v1/admin/billing/products/${missingId}`],
  ["GET", "/v1/admin/billing/payments"],
  ["GET", `/v1/admin/billing/payments/${missingId}`],
  ["GET", "/v1/admin/billing/orders"],
  ["GET", `/v1/admin/billing/orders/${missingId}`],
  ["GET", "/v1/admin/billing/refunds"],
  ["GET", `/v1/admin/billing/refunds/${missingId}`],
  ["GET", "/v1/admin/billing/subscriptions"],
  ["GET", `/v1/admin/billing/subscriptions/${missingId}`],
  ["GET", "/v1/admin/billing/reconciliation/runs"],
  ["GET", `/v1/admin/billing/reconciliation/runs/${missingId}`],
  ["GET", "/v1/admin/billing/analytics/revenue"],
  ["GET", "/v1/admin/billing/analytics/subscriptions"],
  ["GET", "/v1/admin/billing/analytics/credits"],
  ["GET", `/v1/admin/billing/users/${missingId}/credits`],
  ["GET", `/v1/admin/billing/users/${missingId}/credits/ledger`],
];

const WEBHOOK_ENDPOINTS: Endpoint[] = [
  ["GET", "/v1/admin/billing/webhooks"],
  ["GET", `/v1/admin/billing/webhooks/${missingId}`],
  ["POST", `/v1/admin/billing/webhooks/${missingId}/reprocess`],
];

const PRODUCT_WRITE_ENDPOINTS: Endpoint[] = [
  [
    "POST",
    "/v1/admin/billing/products",
    {
      code: "forbidden_pack",
      kind: "credit_pack",
      name: "Forbidden pack",
      pricePaise: 100,
      creditsGranted: 1,
    },
  ],
  ["PATCH", `/v1/admin/billing/products/${missingId}`, { version: 1, name: "Renamed" }],
  ["POST", `/v1/admin/billing/products/${missingId}/duplicate`],
  ["POST", `/v1/admin/billing/products/${missingId}/activate`],
  ["POST", `/v1/admin/billing/products/${missingId}/deactivate`],
  ["POST", `/v1/admin/billing/products/${missingId}/sync-plan`],
];

const REFUND_ENDPOINTS: Endpoint[] = [
  [
    "POST",
    `/v1/admin/billing/payments/${missingId}/refunds`,
    { amountPaise: 100, reason: "not allowed" },
  ],
  ["POST", `/v1/admin/billing/subscriptions/${missingId}/cancel`, { immediately: false }],
];

const ADJUST_ENDPOINTS: Endpoint[] = [
  [
    "POST",
    `/v1/admin/billing/users/${missingId}/credits/adjust`,
    { delta: 1, reason: "not allowed" },
  ],
];

const ALL_ENDPOINTS = [
  ...READ_ENDPOINTS,
  ...WEBHOOK_ENDPOINTS,
  ...PRODUCT_WRITE_ENDPOINTS,
  ...REFUND_ENDPOINTS,
  ...ADJUST_ENDPOINTS,
];

async function statusOf(session: BillingSession, endpoint: Endpoint): Promise<number> {
  const [method, path, body] = endpoint;
  const response = await session.auth.send(method, path, body, {
    "Idempotency-Key": randomUUID(),
  });
  return response.status();
}

async function statuses(session: BillingSession, endpoints: Endpoint[]): Promise<number[]> {
  const results: number[] = [];
  for (const endpoint of endpoints) {
    results.push(await statusOf(session, endpoint));
  }
  return results;
}

test("billing admin endpoints reject anonymous callers", async ({ request }) => {
  const anonymous = new BillingSession(request);

  const results = await statuses(anonymous, ALL_ENDPOINTS);

  expect(new Set(results)).toEqual(new Set([401]));
});

test("a plain user is forbidden from every billing admin endpoint", async ({ request }) => {
  const user = new BillingSession(request);
  await user.signup();

  const results = await statuses(user, ALL_ENDPOINTS);

  expect(new Set(results)).toEqual(new Set([403]));
  const forbidden = await user.auth.send("GET", "/v1/admin/billing/payments");
  expect(forbidden.status()).toBe(403);
  expect(forbidden.headers()["content-type"]).toBe(PROBLEM_JSON);
});

test("an admin can read and manage products and webhooks but cannot refund or adjust credits", async ({
  request,
}) => {
  const admin = await signupWithRole(request, "admin");

  const allowedReads = await statuses(admin, [
    ["GET", "/v1/admin/billing/products"],
    ["GET", "/v1/admin/billing/webhooks"],
  ]);
  const missingRecords = await statuses(admin, [
    ["GET", `/v1/admin/billing/payments/${missingId}`],
    ["POST", `/v1/admin/billing/products/${missingId}/activate`],
  ]);
  const deniedRefunds = await statuses(admin, REFUND_ENDPOINTS);
  const deniedAdjustments = await statuses(admin, ADJUST_ENDPOINTS);

  expect(allowedReads).toEqual([200, 200]);
  expect(missingRecords).toEqual([404, 404]);
  expect(deniedRefunds).toEqual([403, 403]);
  expect(deniedAdjustments).toEqual([403]);
});

test("a super admin passes every billing permission check", async ({ request }) => {
  const superAdmin = await signupWithRole(request, "super_admin");

  const results = await statuses(superAdmin, [...REFUND_ENDPOINTS, ...ADJUST_ENDPOINTS]);

  expect(results).not.toContain(401);
  expect(results).not.toContain(403);
});
