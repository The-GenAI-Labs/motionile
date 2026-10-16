import { expect, test } from "@playwright/test";

import { authOrigin, configureBrowser, password, registerApi } from "../../support/browser-auth.js";

test.beforeEach(async ({ context }) => {
  await configureBrowser(context);
});

test("visible idle sessions refresh silently past the original access expiry", async ({
  page,
  context,
}) => {
  await registerApi(page);
  const original = (await context.cookies()).find((cookie) => cookie.name === "mo_auth");
  expect(original).toBeDefined();
  const expiry = Number(original?.value) * 1000;
  expect(expiry - Date.now()).toBeLessThanOrEqual(75000);
  await page.goto("/dashboard");
  await expect
    .poll(
      async () => {
        const hint = (await context.cookies()).find((cookie) => cookie.name === "mo_auth");
        return Number(hint?.value);
      },
      { timeout: 30000 },
    )
    .toBeGreaterThan(Number(original?.value));
  await expect
    .poll(() => Date.now(), { timeout: 80000, intervals: [1000] })
    .toBeGreaterThan(expiry + 5000);
  await page.goto("/settings/security");
  await expect(page.getByRole("heading", { name: "Security", exact: true })).toBeVisible();
  await expect(page).toHaveURL(/\/settings\/security$/);
});

test("two tabs coordinate refresh and broadcast sign-out", async ({ page, context }) => {
  await registerApi(page);
  const second = await context.newPage();
  const refreshes: number[] = [];
  context.on("response", (response) => {
    if (new URL(response.url()).pathname === "/v1/auth/refresh") refreshes.push(response.status());
  });
  await Promise.all([page.goto("/dashboard"), second.goto("/dashboard")]);
  await expect.poll(() => refreshes.length, { timeout: 30000 }).toBeGreaterThan(0);
  expect(refreshes).toEqual([204]);
  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByRole("menuitem", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(/\/login(?:\?|$)/);
  await expect(second).toHaveURL(/\/login(?:\?|$)/);
  expect(refreshes).not.toContain(401);
});

test("revocation from another context redirects once and preserves the destination", async ({
  page,
  browser,
}) => {
  const identifier = await registerApi(page);
  await page.goto("/settings/security");
  const other = await browser.newContext({ ignoreHTTPSErrors: true });
  await configureBrowser(other);
  try {
    const login = await other.request.post(`${authOrigin}/v1/auth/login`, {
      headers: { Origin: authOrigin, "X-Turnstile-Token": "fake-pass" },
      data: { identifier, password },
    });
    expect(login.status()).toBe(200);
    const sessions = await other.request.get(`${authOrigin}/v1/auth/sessions`);
    const body = (await sessions.json()) as { items: { id: string; current: boolean }[] };
    const target = body.items.find((session) => !session.current);
    expect(target).toBeDefined();
    const csrf = (await other.cookies()).find((cookie) => cookie.name === "mo_csrf")?.value ?? "";
    const revoked = await other.request.delete(`${authOrigin}/v1/auth/sessions/${target?.id}`, {
      headers: { Origin: authOrigin, "X-CSRF-Token": csrf },
    });
    expect(revoked.status()).toBe(204);
    const logins: string[] = [];
    page.on("framenavigated", (frame) => {
      if (frame === page.mainFrame() && new URL(frame.url()).pathname === "/login")
        logins.push(frame.url());
    });
    await page.reload();
    await expect(page).toHaveURL(/\/login\?next=%2Fsettings%2Fsecurity&reason=expired/);
    await expect(page.getByRole("button", { name: "Sign in", exact: true })).toBeVisible();
    expect(logins).toHaveLength(1);
  } finally {
    await other.close();
  }
});

test("failed refresh makes one request and reaches login without a loop", async ({
  page,
  context,
}) => {
  await registerApi(page);
  await context.clearCookies({ name: "__Secure-mo_rt" });
  await context.clearCookies({ name: "__Secure-mo_at" });
  await context.addCookies([{ name: "mo_auth", value: "1", url: authOrigin, secure: true }]);
  let calls = 0;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/v1/auth/refresh") calls += 1;
  });
  await page.goto("/refresh?next=%2Fsettings%2Fsecurity");
  await expect(page).toHaveURL(/\/login\?next=%2Fsettings%2Fsecurity&reason=expired/);
  expect(calls).toBe(1);
  await page.goto("/refresh?next=%2Fsettings%2Fsecurity");
  await expect(page).toHaveURL(/\/login\?next=%2Fsettings%2Fsecurity&reason=expired/);
  expect(calls).toBe(1);
});
