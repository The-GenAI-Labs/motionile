import { expect, test } from "@playwright/test";

import { FakeRazorpay } from "../../support/billing.js";
import {
  expectWalletTotal,
  orderStatusUrl,
  payInSimulatedCheckout,
} from "../../support/billing-ui.js";
import { configureBrowser, registerApi } from "../../support/browser-auth.js";

test.beforeEach(async ({ context }) => {
  await configureBrowser(context);
});

test("a subscription grants credits on each charge, switches plan at the cycle end and cancels at the period end", async ({
  page,
  request,
}) => {
  test.setTimeout(240000);
  const fake = new FakeRazorpay(request);
  await registerApi(page);
  await page.goto("/billing/plans");

  const created = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/v1/billing/subscriptions",
  );
  await page.getByRole("button", { name: "Subscribe to Pro", exact: true }).click();
  const { razorpaySubscriptionId } = (await (await created).json()) as {
    razorpaySubscriptionId: string;
  };
  await payInSimulatedCheckout(page, "Pay successfully");

  await expect(page).toHaveURL(orderStatusUrl);
  await expect(page.getByRole("heading", { name: "Payment received" })).toBeVisible({
    timeout: 60000,
  });
  await expectWalletTotal(page, 300);

  await fake.transitionSubscription(razorpaySubscriptionId, "charged");
  await expectWalletTotal(page, 600);

  await page.goto("/billing/plans");
  await page
    .getByRole("article", { name: "Team", exact: true })
    .getByRole("button", { name: "Switch from next cycle", exact: true })
    .click();
  await page
    .getByRole("alertdialog", { name: "Switch to Team monthly?", exact: true })
    .getByRole("button", { name: "Switch plan", exact: true })
    .click();
  await expect(
    page.getByText("Your plan change is scheduled for the start of your next billing period."),
  ).toBeVisible();
  await expect(
    page.getByRole("note").filter({ hasText: "Your plan changes to Team monthly" }),
  ).toBeVisible();

  await fake.transitionSubscription(razorpaySubscriptionId, "charged");
  await expectWalletTotal(page, 1800);

  await page.goto("/billing/plans");
  const currentPlan = page.getByRole("region", { name: "Current plan", exact: true });
  await expect(currentPlan).toContainText("Team monthly");
  await expect(currentPlan).toContainText("Active");

  await page.getByRole("button", { name: "Cancel subscription", exact: true }).click();
  await page
    .getByRole("alertdialog", { name: "Cancel your subscription?", exact: true })
    .getByRole("button", { name: "Cancel subscription", exact: true })
    .click();
  await expect(page.getByText("Your cancellation has been recorded.")).toBeVisible();
  await expect(
    page.getByRole("note").filter({ hasText: "Your subscription ends on" }),
  ).toBeVisible();
  await expectWalletTotal(page, 1800);
});
