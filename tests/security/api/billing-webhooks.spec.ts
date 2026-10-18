import { expect, test } from "@playwright/test";

import { signupWithRole } from "../../support/admin.js";
import {
  BillingSession,
  creditsOf,
  type CursorPage,
  expectProblem,
  FakeRazorpay,
} from "../../support/billing.js";
import {
  capturedPaymentWebhook,
  newEventId,
  postWebhook,
  receiptOf,
  signWebhook,
  unknownOrderFailure,
} from "../../support/signed-webhook.js";

interface StoredEvent {
  eventId: string;
  status: string;
}

test("a webhook without a signature is rejected", async ({ request }) => {
  const response = await postWebhook(request, unknownOrderFailure(), { signature: null });

  await expectProblem(response, 401, "invalid_webhook_signature");
});

test("a webhook with an invalid signature is rejected", async ({ request }) => {
  const body = unknownOrderFailure();
  const forged = [signWebhook(body, "not-the-webhook-secret"), "0".repeat(64), "not-hex-at-all"];

  for (const signature of forged) {
    await expectProblem(
      await postWebhook(request, body, { signature }),
      401,
      "invalid_webhook_signature",
    );
  }
});

test("a signature computed over a different body is rejected", async ({ request }) => {
  const signature = signWebhook(unknownOrderFailure());

  const response = await postWebhook(request, unknownOrderFailure(), { signature });

  await expectProblem(response, 401, "invalid_webhook_signature");
});

test("a signed webhook without an event id is rejected", async ({ request }) => {
  const response = await postWebhook(request, unknownOrderFailure(), { eventId: null });

  await expectProblem(response, 400, "webhook_event_id_missing");
});

test("a signed webhook that is not a JSON object is rejected", async ({ request }) => {
  const response = await postWebhook(request, "not json");

  await expectProblem(response, 400, "invalid_webhook_payload");
});

test("a replayed event id is acknowledged as a duplicate and grants credits once", async ({
  request,
}) => {
  const customer = new BillingSession(request);
  await customer.signup();
  const fake = new FakeRazorpay(request);
  const checkout = await customer.createOrder("pack_starter");
  const paid = await fake.payOrder(checkout.razorpayOrderId);
  const credits = await creditsOf(customer, "pack_starter");
  const eventId = newEventId();
  const body = capturedPaymentWebhook({
    id: paid.razorpay_payment_id,
    orderId: checkout.razorpayOrderId,
    amountPaise: checkout.amountPaise,
    currency: checkout.currency,
  });

  const first = await postWebhook(request, body, { eventId });
  const replay = await postWebhook(request, body, { eventId });

  expect(first.status()).toBe(200);
  expect(await receiptOf(first)).toBe("received");
  expect(replay.status()).toBe(200);
  expect(await receiptOf(replay)).toBe("duplicate");

  await customer.waitForBalance(credits);

  const lateReplay = await postWebhook(request, body, { eventId });
  expect(await receiptOf(lateReplay)).toBe("duplicate");
  expect((await customer.wallet()).balance).toBe(credits);
  const purchases = (await customer.ledger()).items.filter((entry) => entry.reason === "purchase");
  expect(purchases).toHaveLength(1);
});

test("the same payment delivered under a new event id does not grant credits twice", async ({
  request,
}) => {
  const customer = new BillingSession(request);
  await customer.signup();
  const admin = await signupWithRole(request, "admin");
  const fake = new FakeRazorpay(request);
  const checkout = await customer.createOrder("pack_starter");
  const paid = await fake.payOrder(checkout.razorpayOrderId);
  const credits = await creditsOf(customer, "pack_starter");
  const body = capturedPaymentWebhook({
    id: paid.razorpay_payment_id,
    orderId: checkout.razorpayOrderId,
    amountPaise: checkout.amountPaise,
    currency: checkout.currency,
  });

  expect(await receiptOf(await postWebhook(request, body))).toBe("received");
  await customer.waitForBalance(credits);
  const secondEventId = newEventId();
  expect(await receiptOf(await postWebhook(request, body, { eventId: secondEventId }))).toBe(
    "received",
  );
  await expect
    .poll(
      async () => {
        const page = await admin.json<CursorPage<StoredEvent>>(
          await admin.call(
            "GET",
            "/v1/admin/billing/webhooks?limit=100&eventType=payment.captured",
          ),
          200,
        );
        return page.items.find((event) => event.eventId === secondEventId)?.status;
      },
      { timeout: 60000, intervals: [250, 500, 1000] },
    )
    .toBe("processed");
  const verified = await customer.verifyOrder(paid);

  expect(verified.status()).toBe(200);
  expect((await customer.wallet()).balance).toBe(credits);
  const purchases = (await customer.ledger()).items.filter((entry) => entry.reason === "purchase");
  expect(purchases).toHaveLength(1);
});
