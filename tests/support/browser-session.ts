import { type APIResponse, expect, type Page } from "@playwright/test";

import type { BillingSession } from "./billing.js";
import { authOrigin, signIn } from "./browser-auth.js";

const CSRF_COOKIE = "mo_csrf";

export async function signInAs(page: Page, session: BillingSession): Promise<void> {
  await page.goto("/login");
  await signIn(page, session.auth.email, session.auth.password);
  await expect(page).toHaveURL(/\/dashboard$/);
}

async function csrfToken(page: Page): Promise<string> {
  const cookies = await page.context().cookies(authOrigin);
  return cookies.find((cookie) => cookie.name === CSRF_COOKIE)?.value ?? "";
}

export async function browserApi(
  page: Page,
  method: string,
  path: string,
  data?: Record<string, unknown>,
): Promise<APIResponse> {
  const send = async (): Promise<APIResponse> =>
    page.request.fetch(`${authOrigin}${path}`, {
      method,
      ...(data ? { data } : {}),
      headers: { Origin: authOrigin, "X-CSRF-Token": await csrfToken(page) },
    });
  const response = await send();
  if (response.status() !== 401) return response;
  const refreshed = await page.request.post(`${authOrigin}/v1/auth/refresh`, {
    headers: { Origin: authOrigin, "X-CSRF-Token": await csrfToken(page) },
  });
  expect(refreshed.status()).toBe(204);
  return send();
}
