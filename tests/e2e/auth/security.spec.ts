import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { authOrigin, configureBrowser, registerApi } from "../../support/browser-auth.js";

test.beforeEach(async ({ context }) => {
  await configureBrowser(context);
});

for (const path of ["/login", "/register", "/verify", "/forgot-password", "/reset-password"]) {
  test(`${path} is accessible, noindex, keyboard navigable and CSP compliant`, async ({ page }) => {
    const violations: string[] = [];
    page.on("console", (message) => {
      if (/content security policy|violates.*directive/i.test(message.text()))
        violations.push(message.text());
    });
    await page.addInitScript(() => {
      document.addEventListener("securitypolicyviolation", (event) => {
        document.documentElement.dataset["cspViolation"] =
          `${event.violatedDirective} ${event.blockedURI}`;
      });
    });
    await page.goto(path);
    await expect(page.locator('meta[name="robots"]')).toHaveAttribute("content", /noindex/);
    await page.keyboard.press("Tab");
    expect(await page.evaluate(() => document.activeElement?.tagName)).not.toBe("BODY");
    const report = await new AxeBuilder({ page }).analyze();
    expect(
      report.violations.filter((violation) =>
        ["serious", "critical"].includes(violation.impact ?? ""),
      ),
    ).toEqual([]);
    expect(violations).toEqual([]);
    expect(
      await page.evaluate(() => document.documentElement.dataset["cspViolation"]),
    ).toBeUndefined();
  });
}

test("security settings are accessible and private cookies cannot be read by scripts", async ({
  page,
  context,
}) => {
  await registerApi(page);
  await page.goto("/settings/security");
  await expect(page.getByRole("heading", { name: "Security", exact: true })).toBeVisible();
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute("content", /noindex/);
  const cookies = await context.cookies(`${authOrigin}/v1/auth/me`);
  expect(cookies.find((cookie) => cookie.name === "__Secure-mo_at")?.httpOnly).toBe(true);
  expect(cookies.find((cookie) => cookie.name === "__Secure-mo_rt")?.httpOnly).toBe(true);
  const visible = await page.evaluate(() => document.cookie);
  for (const secret of [
    "__Secure-mo_at",
    "__Secure-mo_rt",
    "__Secure-mo_vt",
    "__Secure-mo_oauth",
  ]) {
    expect(visible).not.toContain(secret);
  }
  const report = await new AxeBuilder({ page }).analyze();
  expect(
    report.violations.filter((violation) =>
      ["serious", "critical"].includes(violation.impact ?? ""),
    ),
  ).toEqual([]);
  await page.goto("/dashboard");
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute("content", /noindex/);
  await page.goto("/admin");
  await expect(page).toHaveURL(/\/forbidden$/);
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute("content", /noindex/);
});

for (const next of [
  "https://evil.example",
  "//evil.example",
  "/\\evil.example",
  "%2f%2fevil.example",
  "javascript:alert(1)",
  "/%255cevil.example",
]) {
  test(`rejects unsafe next ${next} in navigation and OAuth`, async ({ page }) => {
    await page.goto(`/login?next=${encodeURIComponent(next)}`);
    expect(new URL(page.url()).origin).toBe(authOrigin);
    const link = page.getByRole("link", { name: "Continue with Google", exact: true });
    const target = new URL((await link.getAttribute("href")) ?? "", authOrigin);
    expect(target.origin).toBe(authOrigin);
    expect(target.searchParams.get("next")).toBe("/dashboard");
    const response = await page.request.get(
      `${authOrigin}/v1/auth/oauth/google/start?next=${encodeURIComponent(next)}`,
      { maxRedirects: 0 },
    );
    expect(response.status()).toBe(422);
    const body = (await response.json()) as { code: string };
    expect(body.code).toBe("invalid_redirect");
  });
}
