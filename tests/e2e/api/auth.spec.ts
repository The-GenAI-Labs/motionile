import { expect, test } from "@playwright/test";

import { AuthApi, type SessionUser } from "../../support/auth.js";

test("registration, verification, rotation and logout", async ({ request }) => {
  const api = new AuthApi(request);
  const user = await api.signup();
  expect(user.status).toBe("active");
  const me = await api.send("GET", "/v1/auth/me");
  expect(((await me.json()) as SessionUser).id).toBe(user.id);
  expect((await api.send("GET", "/v1/auth/sessions")).status()).toBe(200);
  expect((await api.send("POST", "/v1/auth/refresh")).status()).toBe(204);
  expect((await api.send("POST", "/v1/auth/logout")).status()).toBe(204);
  expect((await api.send("GET", "/v1/auth/me")).status()).toBe(401);
  expect((await api.login()).status()).toBe(200);
  expect((await api.send("POST", "/v1/auth/logout-all")).status()).toBe(204);
});

for (const provider of ["google", "github", "microsoft"]) {
  test("OAuth sign-up, link and unlink using " + provider, async ({ request }) => {
    const api = new AuthApi(request);
    const start = await api.send("GET", "/v1/auth/oauth/" + provider + "/start");
    const approval = new URL(start.headers()["location"] ?? "");
    approval.searchParams.set("email", api.email);
    const approved = await api.send("GET", approval.pathname + approval.search);
    const callback = new URL(approved.headers()["location"] ?? "");
    const completed = await api.send("GET", callback.pathname + callback.search);
    expect(completed.status()).toBe(302);
    expect(completed.headers()["location"]?.endsWith("/dashboard")).toBe(true);
    expect((await api.send("GET", "/v1/auth/me")).status()).toBe(200);
    expect((await api.send("POST", "/v1/auth/password/set/request")).status()).toBe(202);
    expect(
      (
        await api.send("POST", "/v1/auth/password/set", {
          code: await api.code("set_password"),
          newPassword: api.password,
        })
      ).status(),
    ).toBe(204);
    expect((await api.send("DELETE", "/v1/auth/oauth/" + provider)).status()).toBe(204);
    const link = await api.send("GET", "/v1/auth/oauth/" + provider + "/start?intent=link");
    const linkApproval = new URL(link.headers()["location"] ?? "");
    linkApproval.searchParams.set("email", api.email);
    const linkApproved = await api.send("GET", linkApproval.pathname + linkApproval.search);
    const linkCallback = new URL(linkApproved.headers()["location"] ?? "");
    expect((await api.send("GET", linkCallback.pathname + linkCallback.search)).status()).toBe(302);
  });
}

test("unverified password login, resend and contact verification", async ({ request }) => {
  test.setTimeout(150000);
  const api = new AuthApi(request);
  expect((await api.register()).status()).toBe(202);
  const firstCode = await api.code("verify_contact");
  await new Promise((resolve) => setTimeout(resolve, 61000));
  const unverified = await api.login();
  expect(unverified.status()).toBe(403);
  expect(((await unverified.json()) as { code: string }).code).toBe("verification_required");
  const secondCode = await api.code("verify_contact", api.email, firstCode);
  await new Promise((resolve) => setTimeout(resolve, 61000));
  expect((await api.send("POST", "/v1/auth/otp/resend")).status()).toBe(202);
  expect(
    (
      await api.send("POST", "/v1/auth/verify", {
        code: await api.code("verify_contact", api.email, [firstCode, secondCode]),
      })
    ).status(),
  ).toBe(200);
});

test("OTP login and password recovery revoke the expected sessions", async ({ request }) => {
  test.setTimeout(150000);
  const api = new AuthApi(request);
  await api.signup();
  const other = new AuthApi(request);
  expect(
    (
      await other.send("POST", "/v1/auth/login", { identifier: api.email, password: api.password })
    ).status(),
  ).toBe(200);
  const replacement = api.password + "-changed";
  expect(
    (
      await api.send("POST", "/v1/auth/password/change", {
        currentPassword: api.password,
        newPassword: replacement,
      })
    ).status(),
  ).toBe(204);
  expect((await other.send("GET", "/v1/auth/me")).status()).toBe(401);
  expect((await api.send("GET", "/v1/auth/me")).status()).toBe(200);
  await new Promise((resolve) => setTimeout(resolve, 61000));
  expect(
    (await other.send("POST", "/v1/auth/otp/request", { identifier: api.email })).status(),
  ).toBe(202);
  expect(
    (
      await other.send("POST", "/v1/auth/otp/verify", {
        code: await other.code("login", api.email),
      })
    ).status(),
  ).toBe(200);
  await new Promise((resolve) => setTimeout(resolve, 61000));
  expect(
    (await other.send("POST", "/v1/auth/password/forgot", { identifier: api.email })).status(),
  ).toBe(202);
  expect(
    (
      await other.send("POST", "/v1/auth/password/reset", {
        code: await other.code("password_reset", api.email),
        newPassword: api.password,
      })
    ).status(),
  ).toBe(204);
  expect((await api.send("GET", "/v1/auth/me")).status()).toBe(401);
  expect((await other.send("GET", "/v1/auth/me")).status()).toBe(401);
  expect((await api.login()).status()).toBe(200);
  const sessions = await api.send("GET", "/v1/auth/sessions");
  const body = (await sessions.json()) as { items: { id: string }[] };
  expect(
    (await api.send("DELETE", "/v1/auth/sessions/" + (body.items[0]?.id ?? "missing"))).status(),
  ).toBe(204);
});
