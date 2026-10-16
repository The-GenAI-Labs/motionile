import { expect, test } from "@playwright/test";

import {
  authOrigin,
  configureBrowser,
  email,
  enterCode,
  fakeOAuth,
  inboxCode,
  logoutApi,
  password,
  phone,
  registerApi,
  signIn,
} from "../../support/browser-auth.js";

test.beforeEach(async ({ context }) => {
  await configureBrowser(context);
});

for (const kind of ["email", "phone"] as const) {
  test(`registers and verifies a ${kind} contact`, async ({ page }) => {
    const identifier = kind === "email" ? email() : phone();
    await page.goto("/register");
    await page.getByLabel("Name", { exact: true }).fill("Browser user");
    await page.getByLabel("Email or phone", { exact: true }).fill(identifier);
    await page.getByLabel("Password", { exact: true }).fill(password);
    await page.getByLabel("Confirm password", { exact: true }).fill(password);
    await page.getByRole("checkbox").check();
    await page.getByRole("button", { name: "Create account", exact: true }).click();
    await expect(page).toHaveURL(/\/verify(?:\?|$)/);
    await enterCode(page, await inboxCode(page, identifier, "verify_contact"));
    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Browser user");
  });
}

test("password sign-in returns to a protected destination and redirects auth pages", async ({
  page,
}) => {
  const identifier = await registerApi(page);
  await logoutApi(page);
  await page.goto("/settings/security");
  await expect(page).toHaveURL(/\/login\?next=%2Fsettings%2Fsecurity/);
  await signIn(page, identifier);
  await expect(page).toHaveURL(/\/settings\/security$/);
  await page.goto("/register");
  await expect(page).toHaveURL(/\/dashboard$/);
  await page.goto("/admin");
  await expect(page).toHaveURL(/\/forbidden$/);
});

test("an unverified password sign-in completes contact verification", async ({ page }) => {
  const identifier = email();
  const registered = await page.request.post(`${authOrigin}/v1/auth/register`, {
    headers: { Origin: authOrigin, "X-Turnstile-Token": "fake-pass" },
    data: { name: "Unverified user", email: identifier, password },
  });
  expect(registered.status()).toBe(202);
  const originalCode = await inboxCode(page, identifier, "verify_contact");
  const cooldownEnds = Date.now() + 61000;
  await expect
    .poll(() => Date.now(), { timeout: 65000, intervals: [1000] })
    .toBeGreaterThan(cooldownEnds);
  await page.goto("/login");
  await signIn(page, identifier);
  await expect(page).toHaveURL(/\/verify(?:\?|$)/);
  await enterCode(page, await inboxCode(page, identifier, "verify_contact", originalCode));
  await expect(page).toHaveURL(/\/dashboard$/);
});

for (const provider of ["Google", "GitHub", "Microsoft"]) {
  test(`${provider} signs up and signs back in with the fake provider`, async ({ page }) => {
    const identifier = email();
    await page.goto("/login");
    await fakeOAuth(page, identifier, provider);
    const first = await page.request.get(`${authOrigin}/v1/auth/me`);
    const user = (await first.json()) as { id: string };
    await logoutApi(page);
    await page.goto("/login");
    await fakeOAuth(page, identifier, provider);
    const second = await page.request.get(`${authOrigin}/v1/auth/me`);
    expect(((await second.json()) as { id: string }).id).toBe(user.id);
  });
}

test("one-time-code login signs in a verified contact", async ({ page }) => {
  const identifier = email();
  await page.goto("/login");
  await fakeOAuth(page, identifier);
  await logoutApi(page);
  await page.goto("/login");
  await page.getByRole("tab", { name: "One-time code", exact: true }).click();
  await page.getByLabel("Email or phone", { exact: true }).fill(identifier);
  await page.getByRole("button", { name: "Send code", exact: true }).click();
  await expect(page).toHaveURL(/\/verify(?:\?|$)/);
  await enterCode(page, await inboxCode(page, identifier, "login"));
  await expect(page).toHaveURL(/\/dashboard$/);
});

test("forgot password resets credentials and signs in with the new password", async ({ page }) => {
  const identifier = email();
  await page.goto("/login");
  await fakeOAuth(page, identifier);
  await logoutApi(page);
  await page.goto("/forgot-password");
  await page.getByLabel("Email or phone", { exact: true }).fill(identifier);
  await page.getByRole("button", { name: "Send reset code", exact: true }).click();
  await expect(page).toHaveURL(/\/reset-password(?:\?|$)/);
  await page.getByLabel("New password", { exact: true }).fill(password);
  await page.getByLabel("Confirm password", { exact: true }).fill(password);
  await enterCode(page, await inboxCode(page, identifier, "password_reset"));
  await page.getByRole("button", { name: "Reset password", exact: true }).click();
  await expect(page).toHaveURL(/\/login(?:\?|$)/);
  await signIn(page, identifier);
  await expect(page).toHaveURL(/\/dashboard$/);
});
