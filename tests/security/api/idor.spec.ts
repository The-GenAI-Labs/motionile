import { expect, test } from "@playwright/test";

import { AuthApi } from "../../support/auth.js";

test("one user cannot revoke another user's family", async ({ request }) => {
  const first = new AuthApi(request);
  const second = new AuthApi(request);
  await first.signup();
  await second.signup();
  const listed = await first.send("GET", "/v1/auth/sessions");
  const data = (await listed.json()) as { items: { id: string }[] };
  const id = data.items[0]?.id ?? "";
  expect((await second.send("DELETE", "/v1/auth/sessions/" + id)).status()).toBe(404);
  expect((await first.send("GET", "/v1/auth/me")).status()).toBe(200);
});
