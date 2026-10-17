import { randomBytes, randomInt, randomUUID } from "node:crypto";

import { type BrowserContext, expect, type Page } from "@playwright/test";

import { uniqueClientIp } from "../security/api/support.js";

export const authOrigin = process.env["AUTH_WEB_BASE_URL"] ?? "https://localhost:3443";
export const password = "Browser-" + randomBytes(18).toString("base64url");

export function email(): string {
  return `browser-${randomUUID()}@example.com`;
}

export function phone(): string {
  return `+919${randomInt(100000000, 999999999)}`;
}

export async function configureBrowser(context: BrowserContext): Promise<void> {
  await context.setExtraHTTPHeaders({ "X-Forwarded-For": uniqueClientIp() });
}

export async function inboxCode(
  page: Page,
  destination: string,
  template: string,
  previous = "",
): Promise<string> {
  let code = "";
  await expect
    .poll(
      async () => {
        const response = await page.request.get(
          `${authOrigin}/v1/_test/inbox/${encodeURIComponent(destination)}`,
        );
        expect(response.ok()).toBeTruthy();
        const inbox = (await response.json()) as {
          messages: { template: string; code: string | null }[];
        };
        code =
          inbox.messages.find(
            (message) => message.template === template && message.code !== previous,
          )?.code ?? "";
        return code;
      },
      { timeout: 20000 },
    )
    .toMatch(/^\d{6}$/);
  return code;
}

export async function enterCode(page: Page, code: string): Promise<void> {
  await page.getByRole("textbox", { name: "Digit 1", exact: true }).fill(code);
}

export async function registerApi(page: Page, identifier = email()): Promise<string> {
  const result = await page.request.post(`${authOrigin}/v1/auth/register`, {
    headers: { Origin: authOrigin, "X-Turnstile-Token": "fake-pass" },
    data: { name: "Browser user", email: identifier, password },
  });
  expect(result.status()).toBe(202);
  const verified = await page.request.post(`${authOrigin}/v1/auth/verify`, {
    headers: { Origin: authOrigin },
    data: { code: await inboxCode(page, identifier, "verify_contact") },
  });
  expect(verified.status()).toBe(200);
  return identifier;
}

export async function logoutApi(page: Page): Promise<void> {
  const csrf = (await page.context().cookies()).find((cookie) => cookie.name === "mo_csrf")?.value;
  const response = await page.request.post(`${authOrigin}/v1/auth/logout`, {
    headers: { Origin: authOrigin, "X-CSRF-Token": csrf ?? "" },
  });
  expect(response.status()).toBe(204);
}

export async function gotoAfterLogout(page: Page, path: string): Promise<void> {
  try {
    await page.goto(path);
  } catch (error) {
    if (!(error instanceof Error) || !error.message.includes("ERR_ABORTED")) throw error;
    await page.waitForLoadState("domcontentloaded");
    if (new URL(page.url()).pathname !== path) await page.goto(path);
  }
}

export async function signIn(page: Page, identifier: string, secret = password): Promise<void> {
  await page.getByLabel("Email or phone", { exact: true }).fill(identifier);
  await page.locator("#password").fill(secret);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
}

export async function fakeOAuth(
  page: Page,
  identifier: string,
  provider = "Google",
): Promise<void> {
  const link = page.getByRole("link", { name: `Continue with ${provider}`, exact: true });
  const href = await link.getAttribute("href");
  expect(href).not.toBeNull();
  const start = await page.request.get(new URL(href ?? "", authOrigin).toString(), {
    maxRedirects: 0,
  });
  expect(start.status()).toBe(302);
  const authorization = new URL(start.headers()["location"] ?? "", authOrigin);
  authorization.searchParams.set("email", identifier);
  await page.goto(authorization.toString());
  await expect(page).toHaveURL(/\/dashboard$/);
}
