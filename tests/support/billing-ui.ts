import { expect, type Locator, type Page } from "@playwright/test";

export const orderStatusUrl =
  /\/billing\/status\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

const RELOAD_INTERVALS = [1000, 2000, 3000];

export function formatCredits(credits: number): string {
  return new Intl.NumberFormat("en-IN").format(credits);
}

export function walletTotal(page: Page): Locator {
  return page
    .getByRole("region", { name: "Your credits", exact: true })
    .locator("dl > div")
    .filter({ has: page.getByText("Total", { exact: true }) })
    .locator("dd");
}

export async function expectWalletTotal(
  page: Page,
  credits: number,
  path = "/billing",
  timeout = 60000,
): Promise<void> {
  await expect(async () => {
    await page.goto(path);
    await expect(walletTotal(page)).toHaveText(formatCredits(credits), { timeout: 5000 });
  }).toPass({ timeout, intervals: RELOAD_INTERVALS });
}

export async function payInSimulatedCheckout(
  page: Page,
  action: "Pay successfully" | "Pay and skip verification",
): Promise<void> {
  await page
    .getByRole("dialog", { name: "Simulated checkout", exact: true })
    .getByRole("button", { name: action, exact: true })
    .click();
}
