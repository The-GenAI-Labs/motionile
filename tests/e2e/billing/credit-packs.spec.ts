import { expect, test } from "@playwright/test";

import {
  expectWalletTotal,
  orderStatusUrl,
  payInSimulatedCheckout,
  walletTotal,
} from "../../support/billing-ui.js";
import { configureBrowser, registerApi } from "../../support/browser-auth.js";

test.beforeEach(async ({ context }) => {
  await configureBrowser(context);
});

test("buying a credit pack from the billing page adds its credits to the wallet", async ({
  page,
}) => {
  await registerApi(page);
  await page.goto("/billing/credits");
  await expect(walletTotal(page)).toHaveText("0");

  await page.getByRole("button", { name: "Buy Starter", exact: true }).click();
  await payInSimulatedCheckout(page, "Pay successfully");

  await expect(page).toHaveURL(orderStatusUrl);
  await expect(page.getByRole("heading", { name: "Payment received" })).toBeVisible();
  await expect(page.getByText("100 credits were added to your wallet.")).toBeVisible();
  await expectWalletTotal(page, 100);
});

test("a payment confirmed only by webhook settles after the checkout tab is closed", async ({
  page,
  context,
}) => {
  await registerApi(page);
  await page.goto("/billing/credits");
  await page.getByRole("button", { name: "Buy Starter", exact: true }).click();
  await payInSimulatedCheckout(page, "Pay and skip verification");
  await expect(page).toHaveURL(orderStatusUrl);
  const statusPath = new URL(page.url()).pathname;
  await page.close();

  const reopened = await context.newPage();
  await reopened.goto(statusPath);
  await expect(reopened.getByRole("heading", { name: "Payment received" })).toBeVisible({
    timeout: 60000,
  });
  await expect(reopened.getByText("100 credits were added to your wallet.")).toBeVisible();
  await expectWalletTotal(reopened, 100);
});

test("a failed payment leaves the wallet unchanged", async ({ page }) => {
  await registerApi(page);
  await page.goto("/billing/credits");
  await page.getByRole("button", { name: "Buy Starter", exact: true }).click();
  const checkout = page.getByRole("dialog", { name: "Simulated checkout", exact: true });
  await checkout.getByRole("button", { name: "Fail payment", exact: true }).click();

  await expect(checkout.getByRole("alert")).toContainText("Payment failed");
  await expectWalletTotal(page, 0, "/billing/credits");
});
