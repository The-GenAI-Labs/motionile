import { expect, test } from "@playwright/test";

import { AuthApi } from "../../support/auth.js";

for (const route of ["register", "login", "otp/request", "password/forgot"]) {
  test(route + " rejects missing and failed Turnstile proofs", async ({ request }) => {
    const api = new AuthApi(request);
    const body =
      route === "register"
        ? { name: "Turnstile", email: api.email, password: api.password }
        : route === "login"
          ? { identifier: api.email, password: api.password }
          : { identifier: api.email };
    expect(
      (await api.send("POST", "/v1/auth/" + route, body, { "X-Turnstile-Token": "" })).status(),
    ).toBe(400);
    expect(
      (await api.send("POST", "/v1/auth/" + route, body, { "X-Turnstile-Token": "fail" })).status(),
    ).toBe(403);
  });
}
