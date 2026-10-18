import { randomUUID } from "node:crypto";

import { type APIRequestContext, expect, test } from "@playwright/test";

import {
  BillingSession,
  creditsOf,
  expectProblem,
  FakeRazorpay,
  type Verified,
} from "../../support/billing.js";

async function twoCustomers(request: APIRequestContext): Promise<[BillingSession, BillingSession]> {
  const owner = new BillingSession(request);
  const intruder = new BillingSession(request);
  await owner.signup();
  await intruder.signup();
  return [owner, intruder];
}

test("another user cannot read an order", async ({ request }) => {
  const [owner, intruder] = await twoCustomers(request);
  const checkout = await owner.createOrder("pack_starter");

  const stolen = await intruder.call("GET", `/v1/billing/orders/${checkout.orderId}`);
  const own = await owner.call("GET", `/v1/billing/orders/${checkout.orderId}`);

  await expectProblem(stolen, 404, "order_not_found");
  expect(own.status()).toBe(200);
  await expectProblem(
    await intruder.call("GET", `/v1/billing/orders/${randomUUID()}`),
    404,
    "order_not_found",
  );
});

test("another user cannot verify or settle someone else's payment", async ({ request }) => {
  const [owner, intruder] = await twoCustomers(request);
  const fake = new FakeRazorpay(request);
  const checkout = await owner.createOrder("pack_starter");
  const paid = await fake.payOrder(checkout.razorpayOrderId);

  const attempt = await intruder.verifyOrder(paid);

  await expectProblem(attempt, 404, "order_not_found");
  expect((await intruder.wallet()).balance).toBe(0);
  const credits = await creditsOf(owner, "pack_starter");
  const settled = await owner.json<Verified>(await owner.verifyOrder(paid), 200);
  expect(settled.status).toBe("paid");
  expect(settled.creditsGranted).toBe(credits);
  expect((await owner.wallet()).balance).toBe(credits);
  expect((await intruder.wallet()).balance).toBe(0);
});

test("another user cannot verify someone else's subscription", async ({ request }) => {
  const [owner, intruder] = await twoCustomers(request);
  const fake = new FakeRazorpay(request);
  const checkout = await owner.createSubscription("pro_monthly");
  const authorized = await fake.authorizeSubscription(checkout.razorpaySubscriptionId);

  const attempt = await intruder.verifySubscription(authorized);

  await expectProblem(attempt, 404, "subscription_not_found");
  expect(await intruder.subscription()).toBeNull();
});

test("history, wallet and ledger only show the caller's own records", async ({ request }) => {
  const [owner, intruder] = await twoCustomers(request);
  const fake = new FakeRazorpay(request);
  const checkout = await owner.createOrder("pack_starter");
  const paid = await fake.payOrder(checkout.razorpayOrderId);
  await owner.verifyOrder(paid);
  const credits = await creditsOf(owner, "pack_starter");

  const ownerHistory = (await owner.history()).items;
  const intruderHistory = (await intruder.history()).items;
  const ownerLedger = (await owner.ledger()).items;
  const intruderLedger = (await intruder.ledger()).items;

  expect(ownerHistory.some((item) => item.orderId === checkout.orderId)).toBe(true);
  expect(intruderHistory).toEqual([]);
  expect(ownerLedger.some((entry) => entry.reason === "purchase")).toBe(true);
  expect(intruderLedger).toEqual([]);
  expect((await owner.wallet()).balance).toBe(credits);
  expect((await intruder.wallet()).balance).toBe(0);
});

test("billing endpoints require a session", async ({ request }) => {
  const anonymous = new BillingSession(request);
  const paths = [
    ["GET", "/v1/billing/history"],
    ["GET", "/v1/billing/subscription"],
    ["GET", `/v1/billing/orders/${randomUUID()}`],
    ["GET", "/v1/credits/wallet"],
    ["GET", "/v1/credits/ledger"],
    ["POST", "/v1/billing/orders"],
    ["POST", "/v1/billing/subscription/cancel"],
  ] as const;

  for (const [method, path] of paths) {
    const response = await anonymous.auth.send(
      method,
      path,
      method === "POST" ? { productCode: "pack_starter" } : undefined,
      { "Idempotency-Key": randomUUID() },
    );

    expect(response.status(), `${method} ${path}`).toBe(401);
  }
});
