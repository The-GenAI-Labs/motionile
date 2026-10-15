import { expect, test } from "@playwright/test";

import { AuthApi } from "../../support/auth.js";

test("authenticated mutations require a matching CSRF token", async ({ request }) => {
  const api = new AuthApi(request);
  await api.signup();
  for (const token of ["", "wrong"]) {
    expect(
      (await api.send("POST", "/v1/auth/logout", undefined, { "X-CSRF-Token": token })).status(),
    ).toBe(403);
    expect(
      (await api.send("POST", "/v1/auth/refresh", undefined, { "X-CSRF-Token": token })).status(),
    ).toBe(403);
  }
  expect((await api.send("GET", "/v1/auth/me")).status()).toBe(200);
});
