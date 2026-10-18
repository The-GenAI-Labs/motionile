import { expect, test } from "@playwright/test";

import { signupWithRole } from "../../support/admin.js";
import { BillingSession, buyPack, FakeRazorpay, type Refund } from "../../support/billing.js";
import { configureBrowser, signIn } from "../../support/browser-auth.js";

const REFUND_PAISE = 9950;
const CLAWED_BACK_CREDITS = 50;

test.beforeEach(async ({ context }) => {
  await configureBrowser(context);
});

test("a super admin refunds part of a payment and the customer's wallet and ledger show the clawback", async ({
  page,
  request,
}) => {
  test.setTimeout(240000);
  const fake = new FakeRazorpay(request);
  const customer = new BillingSession(request);
  await customer.signup();
  const admin = await signupWithRole(request, "super_admin");

  const { checkout } = await buyPack(customer, fake);
  await customer.waitForBalance(100);
  const paymentId = await customer.paymentIdForOrder(checkout.orderId);

  const refund = await admin.json<Refund>(
    await admin.keyed("POST", `/v1/admin/billing/payments/${paymentId}/refunds`, {
      amountPaise: REFUND_PAISE,
      reason: "e2e partial refund",
    }),
    201,
  );
  expect(refund.status).toBe("pending");
  expect(refund.amountPaise).toBe(REFUND_PAISE);
  const razorpayRefundId = refund.razorpayRefundId ?? "";
  expect(razorpayRefundId).not.toBe("");

  await fake.settleRefund(razorpayRefundId, "processed");
  await fake.deliverRefundProcessed(razorpayRefundId);
  await customer.waitForBalance(100 - CLAWED_BACK_CREDITS);

  const ledger = await customer.ledger();
  const clawback = ledger.items.find((entry) => entry.reason === "refund_clawback");
  expect(clawback?.delta).toBe(-CLAWED_BACK_CREDITS);
  expect(clawback?.refType).toBe("refund");

  const history = await customer.history();
  const refundItem = history.items.find((item) => item.type === "refund");
  expect(refundItem?.status).toBe("processed");
  expect(refundItem?.amountPaise).toBe(REFUND_PAISE);

  await page.goto("/login");
  await signIn(page, admin.auth.email, admin.auth.password);
  await expect(page).toHaveURL(/\/dashboard$/);
  await page.goto(`/admin/billing/payments/${paymentId}`);
  const refunds = page.getByRole("region", { name: "Refunds", exact: true });
  const row = refunds.getByRole("row").filter({ hasText: "99.50" });
  await expect(row).toBeVisible();
  await expect(row.getByRole("cell").nth(4)).toHaveText(String(CLAWED_BACK_CREDITS));
});
