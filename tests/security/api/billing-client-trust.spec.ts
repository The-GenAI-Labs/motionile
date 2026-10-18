import { randomUUID } from "node:crypto";

import { expect, test } from "@playwright/test";

import {
  BillingSession,
  expectProblem,
  FakeRazorpay,
  type Verified,
} from "../../support/billing.js";

const FORBIDDEN_MONEY_FIELDS: Record<string, unknown>[] = [
  { amountPaise: 1 },
  { amount: 1 },
  { pricePaise: 1 },
  { currency: "USD" },
  { creditsGranted: 1000000 },
  { credits: 1000000 },
  { userId: randomUUID() },
];

test("order creation rejects any client supplied money field", async ({ request }) => {
  const session = new BillingSession(request);
  await session.signup();

  for (const extra of FORBIDDEN_MONEY_FIELDS) {
    const response = await session.keyed("POST", "/v1/billing/orders", {
      productCode: "pack_starter",
      ...extra,
    });

    await expectProblem(response, 422, "validation_failed");
  }
  expect((await session.history()).items).toEqual([]);
});

test("subscription creation and plan change reject any client supplied money field", async ({
  request,
}) => {
  const session = new BillingSession(request);
  await session.signup();

  for (const extra of FORBIDDEN_MONEY_FIELDS) {
    await expectProblem(
      await session.keyed("POST", "/v1/billing/subscriptions", {
        productCode: "pro_monthly",
        ...extra,
      }),
      422,
      "validation_failed",
    );
    await expectProblem(
      await session.call("POST", "/v1/billing/subscription/change", {
        productCode: "team_monthly",
        ...extra,
      }),
      422,
      "validation_failed",
    );
  }
  expect(await session.subscription()).toBeNull();
});

test("the order amount and currency come from the product", async ({ request }) => {
  const session = new BillingSession(request);
  await session.signup();
  const products = await session.products();
  const pack = products.creditPacks.find((item) => item.code === "pack_starter");

  const checkout = await session.createOrder("pack_starter");

  expect(pack).toBeDefined();
  expect(checkout.amountPaise).toBe(pack?.pricePaise);
  expect(checkout.currency).toBe(pack?.currency);
});

test("an unknown product code cannot be ordered", async ({ request }) => {
  const session = new BillingSession(request);
  await session.signup();

  const response = await session.keyed("POST", "/v1/billing/orders", {
    productCode: "pack_does_not_exist",
  });

  await expectProblem(response, 404, "product_not_found");
});

test("a subscription product cannot be bought as a credit pack order", async ({ request }) => {
  const session = new BillingSession(request);
  await session.signup();

  const response = await session.keyed("POST", "/v1/billing/orders", {
    productCode: "pro_monthly",
  });

  await expectProblem(response, 422, "product_not_purchasable");
});

for (const mismatch of [
  { label: "an underpaid amount", options: { amountPaise: 100 } },
  { label: "a different currency", options: { currency: "USD" } },
]) {
  test(`verifying a payment with ${mismatch.label} grants no credits`, async ({ request }) => {
    const session = new BillingSession(request);
    await session.signup();
    const fake = new FakeRazorpay(request);
    const checkout = await session.createOrder("pack_starter");
    const paid = await fake.payOrder(checkout.razorpayOrderId, mismatch.options);

    const verified = await session.json<Verified>(await session.verifyOrder(paid), 200);

    expect(verified.status).toBe("pending");
    expect(verified.creditsGranted).toBe(0);
    expect((await session.wallet()).balance).toBe(0);
    const order = await session.json<{ status: string; creditsGranted: number }>(
      await session.call("GET", `/v1/billing/orders/${checkout.orderId}`),
      200,
    );
    expect(order.status).not.toBe("paid");
    expect(order.creditsGranted).toBe(0);
  });
}

test("a tampered payment signature is rejected and grants nothing", async ({ request }) => {
  const session = new BillingSession(request);
  await session.signup();
  const fake = new FakeRazorpay(request);
  const checkout = await session.createOrder("pack_starter");
  const paid = await fake.payOrder(checkout.razorpayOrderId);

  const response = await session.verifyOrder({ ...paid, razorpay_signature: "0".repeat(64) });

  await expectProblem(response, 400, "invalid_payment_signature");
  expect((await session.wallet()).balance).toBe(0);
});
