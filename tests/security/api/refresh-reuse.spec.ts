import { expect, test } from "@playwright/test";

import { AuthApi } from "../../support/auth.js";
import type { Problem } from "./support.js";

test("refresh reuse outside grace revokes access immediately", async ({ request }) => {
  test.slow();
  const api = new AuthApi(request);
  await api.signup();
  const original = api.cookies.get("__Secure-mo_rt") ?? "";
  expect((await api.send("POST", "/v1/auth/refresh")).status()).toBe(204);
  const current = api.cookies.get("__Secure-mo_rt") ?? "";
  api.cookies.set("__Secure-mo_rt", original);
  const conflict = await api.send("POST", "/v1/auth/refresh");
  expect(((await conflict.json()) as Problem).code).toBe("refresh_conflict");
  await new Promise((resolve) => setTimeout(resolve, 11000));
  const reused = await api.send("POST", "/v1/auth/refresh");
  expect(((await reused.json()) as Problem).code).toBe("refresh_reused");
  api.cookies.set("__Secure-mo_rt", current);
  expect((await api.send("GET", "/v1/auth/me")).status()).toBe(401);
});
