import { randomBytes, randomUUID } from "node:crypto";

import { type APIRequestContext, type APIResponse, expect } from "@playwright/test";

import { ALLOWED_ORIGIN, uniqueClientIp } from "../security/api/support.js";

export interface SessionUser {
  id: string;
  status: string;
  hasPassword: boolean;
  linkedProviders: string[];
}
interface Inbox {
  messages: { template: string; code: string | null }[];
}
export class AuthApi {
  readonly cookies = new Map<string, string>();
  readonly email = "auth-" + randomUUID() + "@example.com";
  readonly password = randomBytes(24).toString("base64url");
  readonly ip = uniqueClientIp();
  readonly baseUrl = process.env["API_BASE_URL"] ?? "http://localhost:8000";
  constructor(readonly request: APIRequestContext) {}

  async send(
    method: string,
    path: string,
    data?: Record<string, unknown>,
    extra: Record<string, string> = {},
  ): Promise<APIResponse> {
    const response = await this.request.fetch(new URL(path, this.baseUrl).toString(), {
      method,
      ...(data ? { data } : {}),
      maxRedirects: 0,
      headers: {
        Origin: ALLOWED_ORIGIN,
        "X-Forwarded-For": this.ip,
        "X-Turnstile-Token": "fake-pass",
        "X-CSRF-Token": this.cookies.get("mo_csrf") ?? "",
        Cookie: [...this.cookies].map(([name, value]) => name + "=" + value).join("; "),
        ...extra,
      },
    });
    for (const header of response.headersArray()) {
      if (header.name.toLowerCase() !== "set-cookie") continue;
      const pair = header.value.split(";", 1)[0] ?? "";
      const index = pair.indexOf("=");
      const name = pair.slice(0, index);
      if (/max-age=0(?:;|$)/i.test(header.value)) this.cookies.delete(name);
      else this.cookies.set(name, pair.slice(index + 1));
    }
    return response;
  }
  async code(
    template: string,
    destination = this.email,
    previous: string | readonly string[] = "",
  ): Promise<string> {
    let result = "";
    const previousCodes = new Set(typeof previous === "string" ? [previous] : previous);
    await expect
      .poll(
        async () => {
          const inbox = await this.send(
            "GET",
            "/v1/_test/inbox/" + encodeURIComponent(destination),
          );
          const body = (await inbox.json()) as Inbox;
          result =
            body.messages.find(
              (message) => message.template === template && !previousCodes.has(message.code ?? ""),
            )?.code ?? "";
          return result;
        },
        { timeout: 15000, intervals: [250, 500, 1000] },
      )
      .toMatch(/^[0-9]{6}$/);
    return result;
  }
  async register(): Promise<APIResponse> {
    return this.send("POST", "/v1/auth/register", {
      name: "API test",
      email: this.email,
      password: this.password,
    });
  }
  async signup(): Promise<SessionUser> {
    expect((await this.register()).status()).toBe(202);
    const verified = await this.send("POST", "/v1/auth/verify", {
      code: await this.code("verify_contact"),
    });
    expect(verified.status()).toBe(200);
    return (await verified.json()) as SessionUser;
  }
  async login(): Promise<APIResponse> {
    return this.send("POST", "/v1/auth/login", { identifier: this.email, password: this.password });
  }
}
