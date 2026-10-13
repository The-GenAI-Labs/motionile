import { expect, test } from "@playwright/test";

test("home page presents the product", async ({ page }) => {
  await page.goto("/");

  await expect(page).toHaveTitle(/Motionile/);
  await expect(page.getByRole("heading", { level: 1, name: "Motionile" })).toBeVisible();
  await expect(page.getByRole("link", { name: "See how it works" })).toBeVisible();
});

test("primary button scrolls to how it works", async ({ page }) => {
  await page.goto("/");

  await page.getByRole("link", { name: "See how it works" }).click();

  await expect(page).toHaveURL(/#how-it-works$/);
  await expect(page.getByRole("heading", { name: "How it works" })).toBeInViewport();
});
