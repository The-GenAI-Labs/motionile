import { expect, test } from "@playwright/test";

import { AuthApi } from "../../support/auth.js";
import type { Problem } from "./support.js";

test("credential failures use identical status and problem codes", async ({ request }) => {
  const api = new AuthApi(request);
  await api.signup();
  const absent = new AuthApi(request);
  const existingFailure = await api.send("POST", "/v1/auth/login", {
    identifier: api.email,
    password: "incorrect-value",
  });
  const absentFailure = await absent.send("POST", "/v1/auth/login", {
    identifier: absent.email,
    password: "incorrect-value",
  });
  expect(existingFailure.status()).toBe(absentFailure.status());
  const existingProblem = (await existingFailure.json()) as Problem;
  const absentProblem = (await absentFailure.json()) as Problem;
  expect(existingProblem.code).toBe(absentProblem.code);
  expect(existingProblem.detail).toBe(absentProblem.detail);
});

for (const path of ["/v1/auth/register", "/v1/auth/otp/request", "/v1/auth/password/forgot"]) {
  test(path + " hides account existence", async ({ request }) => {
    test.setTimeout(90000);
    const existing = new AuthApi(request);
    await existing.signup();
    const absent = new AuthApi(request);
    await new Promise((resolve) => setTimeout(resolve, 61000));
    const responses = [];
    for (const api of [existing, absent]) {
      const body = path.endsWith("register")
        ? { name: "API test", email: api.email, password: api.password }
        : { identifier: api.email };
      const response = await api.send("POST", path, body);
      expect(response.status()).toBe(202);
      const value = (await response.json()) as Record<string, unknown>;
      expect(Object.keys(value).sort()).toEqual([
        "channel",
        "destination",
        "expiresIn",
        "resendAfter",
      ]);
      expect(JSON.stringify(value)).not.toContain(api.email);
      responses.push({ ...value, destination: "masked" });
    }
    expect(responses[0]).toEqual(responses[1]);
  });
}
