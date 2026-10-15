import { expect, test } from "@playwright/test";

import { AuthApi } from "../../support/auth.js";

test("auth cookies have their required security attributes", async ({ request }) => {
  const api = new AuthApi(request);
  const registration = await api.register();
  const ticket =
    registration.headersArray().find((header) => header.value.startsWith("__Secure-mo_vt="))
      ?.value ?? "";
  expect(ticket).toMatch(/HttpOnly/i);
  expect(ticket).toMatch(/SameSite=Strict/i);
  expect(ticket).toMatch(/Secure/i);
  const verification = await api.send("POST", "/v1/auth/verify", {
    code: await api.code("verify_contact"),
  });
  const cookies = verification
    .headersArray()
    .filter((header) => header.name.toLowerCase() === "set-cookie");
  for (const cookie of cookies) expect(cookie.value).toMatch(/Secure/i);
  const refresh = cookies.find((header) => header.value.startsWith("__Secure-mo_rt="))?.value ?? "";
  expect(refresh).toMatch(/HttpOnly/i);
  expect(refresh).toMatch(/SameSite=Strict/i);
  expect(refresh).toContain("Path=/v1/auth");
  expect(refresh).not.toMatch(/Domain=/i);
  const access = cookies.find((header) => header.value.startsWith("__Secure-mo_at="))?.value ?? "";
  expect(access).toMatch(/HttpOnly/i);
  expect(access).toContain("Max-Age=900");
  const csrf = cookies.find((header) => header.value.startsWith("mo_csrf="))?.value ?? "";
  expect(csrf).not.toMatch(/HttpOnly/i);
});
