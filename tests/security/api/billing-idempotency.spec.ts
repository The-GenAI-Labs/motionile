import { randomUUID } from "node:crypto";

import { expect, test } from "@playwright/test";

import { signupWithRole } from "../../support/admin.js";
import { BillingSession, expectProblem } from "../../support/billing.js";

const VERIFY_BODY = {
  razorpayOrderId: "order_missingkey",
  razorpayPaymentId: "pay_missingkey",
  razorpaySignature: "missing-key",
};

const SUBSCRIPTION_VERIFY_BODY = {
  razorpayPaymentId: "pay_missingkey",
  razorpaySubscriptionId: "sub_missingkey",
  razorpaySignature: "missing-key",
};

test("customer money endpoints require an Idempotency-Key", async ({ request }) => {
  const session = new BillingSession(request);
  await session.signup();
  const attempts: [string, Record<string, unknown>][] = [
    ["/v1/billing/orders", { productCode: "pack_starter" }],
    ["/v1/billing/subscriptions", { productCode: "pro_monthly" }],
    ["/v1/billing/payments/verify", VERIFY_BODY],
    ["/v1/billing/subscriptions/verify", SUBSCRIPTION_VERIFY_BODY],
  ];

  for (const [path, body] of attempts) {
    await expectProblem(await session.call("POST", path, body), 400, "idempotency_key_required");
  }
  expect((await session.history()).items).toEqual([]);
});

test("admin refunds and credit adjustments require an Idempotency-Key", async ({ request }) => {
  const admin = await signupWithRole(request, "super_admin");

  await expectProblem(
    await admin.call("POST", `/v1/admin/billing/payments/${randomUUID()}/refunds`, {
      amountPaise: 100,
      reason: "missing key",
    }),
    400,
    "idempotency_key_required",
  );
  await expectProblem(
    await admin.call("POST", `/v1/admin/billing/users/${randomUUID()}/credits/adjust`, {
      delta: 1,
      reason: "missing key",
    }),
    400,
    "idempotency_key_required",
  );
});

test("a malformed Idempotency-Key is rejected", async ({ request }) => {
  const session = new BillingSession(request);
  await session.signup();

  const response = await session.keyed(
    "POST",
    "/v1/billing/orders",
    { productCode: "pack_starter" },
    "has spaces in it",
  );

  await expectProblem(response, 400, "idempotency_key_invalid");
});

test("an order key replays the first response and rejects a different product", async ({
  request,
}) => {
  const session = new BillingSession(request);
  await session.signup();
  const key = randomUUID();
  const body = { productCode: "pack_starter" };

  const first = await session.keyed("POST", "/v1/billing/orders", body, key);
  const replay = await session.keyed("POST", "/v1/billing/orders", body, key);
  const reused = await session.keyed(
    "POST",
    "/v1/billing/orders",
    { productCode: "pack_creator" },
    key,
  );

  expect(first.status()).toBe(201);
  expect(first.headers()["idempotent-replayed"]).toBeUndefined();
  expect(replay.status()).toBe(201);
  expect(replay.headers()["idempotent-replayed"]).toBe("true");
  expect(await replay.json()).toEqual(await first.json());
  await expectProblem(reused, 409, "idempotency_key_reused");
});

test("the same key from two users creates two separate orders", async ({ request }) => {
  const first = new BillingSession(request);
  const second = new BillingSession(request);
  await first.signup();
  await second.signup();
  const key = randomUUID();

  const firstOrder = await first.createOrder("pack_starter", key);
  const secondOrder = await second.createOrder("pack_starter", key);

  expect(secondOrder.orderId).not.toBe(firstOrder.orderId);
});

test("a credit adjustment key replays once and rejects a different amount", async ({ request }) => {
  const admin = await signupWithRole(request, "super_admin");
  const customer = new BillingSession(request);
  await customer.signup();
  const path = `/v1/admin/billing/users/${customer.userId}/credits/adjust`;
  const key = randomUUID();
  const body = { delta: 10, reason: "idempotency check" };

  const first = await admin.keyed("POST", path, body, key);
  const replay = await admin.keyed("POST", path, body, key);
  const reused = await admin.keyed("POST", path, { ...body, delta: 20 }, key);

  expect(first.status()).toBe(201);
  expect(replay.status()).toBe(201);
  expect(replay.headers()["idempotent-replayed"]).toBe("true");
  expect(await replay.json()).toEqual(await first.json());
  await expectProblem(reused, 409, "idempotency_key_reused");
  expect((await customer.wallet()).balance).toBe(10);
});
