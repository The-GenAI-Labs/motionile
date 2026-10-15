import { expect, test } from "@playwright/test";

import { AuthApi } from "../../support/auth.js";

test("JWT signature, algorithm, key, audience and expiry tampering fail", async ({ request }) => {
  const api = new AuthApi(request);
  await api.signup();
  const original = api.cookies.get("__Secure-mo_at") ?? "";
  const [header = "", payload = "", signature = ""] = original.split(".");
  const claims = JSON.parse(Buffer.from(payload, "base64url").toString()) as Record<
    string,
    unknown
  >;
  const encode = (value: Record<string, unknown>): string =>
    Buffer.from(JSON.stringify(value)).toString("base64url");
  const variants = [
    header + "." + payload + ".AAAAAAAA",
    encode({ alg: "none", kid: "local" }) + "." + payload + ".",
    encode({ alg: "EdDSA", kid: "unknown" }) + "." + payload + "." + signature,
    header + "." + encode({ ...claims, exp: 1 }) + "." + signature,
    header + "." + encode({ ...claims, aud: "wrong" }) + "." + signature,
  ];
  for (const token of variants) {
    api.cookies.set("__Secure-mo_at", token);
    expect((await api.send("GET", "/v1/auth/me")).status()).toBe(401);
  }
});
