import { describe, expect, it } from "vitest";

import { env } from "@/config/env";
import {
  DEFAULT_API_URL,
  isLoopbackUrl,
  parsePublicEnv,
  parseServerEnv,
  readPublicEnv,
} from "@/config/env-schema";
import { serverEnv } from "@/config/server-env";

describe("public env", () => {
  it("accepts an https site url and strips trailing slashes", () => {
    expect(parsePublicEnv({ NEXT_PUBLIC_SITE_URL: "https://motionile.com/" })).toEqual({
      NEXT_PUBLIC_SITE_URL: "https://motionile.com",
      NEXT_PUBLIC_API_URL: DEFAULT_API_URL,
      NEXT_PUBLIC_PROVIDERS_MODE: "live",
    });
  });

  it("accepts a local http url", () => {
    expect(
      parsePublicEnv({ NEXT_PUBLIC_SITE_URL: "http://localhost:3000" }).NEXT_PUBLIC_SITE_URL,
    ).toBe("http://localhost:3000");
  });

  it("reads the API and CDN urls and treats empty values as unset", () => {
    expect(
      parsePublicEnv({
        NEXT_PUBLIC_SITE_URL: "https://motionile.com",
        NEXT_PUBLIC_API_URL: "https://api.motionile.com/",
        NEXT_PUBLIC_CDN_URL: "https://cdn.motionile.com",
      }),
    ).toEqual({
      NEXT_PUBLIC_SITE_URL: "https://motionile.com",
      NEXT_PUBLIC_API_URL: "https://api.motionile.com",
      NEXT_PUBLIC_CDN_URL: "https://cdn.motionile.com",
      NEXT_PUBLIC_PROVIDERS_MODE: "live",
    });
    expect(
      parsePublicEnv({
        NEXT_PUBLIC_SITE_URL: "https://motionile.com",
        NEXT_PUBLIC_API_URL: "",
        NEXT_PUBLIC_CDN_URL: "",
      }),
    ).toEqual({
      NEXT_PUBLIC_SITE_URL: "https://motionile.com",
      NEXT_PUBLIC_API_URL: DEFAULT_API_URL,
      NEXT_PUBLIC_PROVIDERS_MODE: "live",
    });
  });

  it("rejects a missing site url", () => {
    expect(() => parsePublicEnv({})).toThrow(/NEXT_PUBLIC_SITE_URL/);
  });

  it("rejects non-http urls", () => {
    expect(() => parsePublicEnv({ NEXT_PUBLIC_SITE_URL: "ftp://motionile.com" })).toThrow(
      /Invalid public environment variables/,
    );
    expect(() =>
      parsePublicEnv({
        NEXT_PUBLIC_SITE_URL: "https://motionile.com",
        NEXT_PUBLIC_API_URL: "javascript:alert(1)",
      }),
    ).toThrow(/NEXT_PUBLIC_API_URL/);
  });

  it("exposes the validated environment", () => {
    expect(env.NEXT_PUBLIC_SITE_URL).toBe("https://motionile.test");
    expect(readPublicEnv()).toEqual(env);
  });
});

describe("providers mode", () => {
  const withMode = (siteUrl: string, mode: string | undefined) =>
    parsePublicEnv({ NEXT_PUBLIC_SITE_URL: siteUrl, NEXT_PUBLIC_PROVIDERS_MODE: mode });

  it("defaults to live providers and treats an empty value as unset", () => {
    expect(withMode("https://motionile.com", undefined).NEXT_PUBLIC_PROVIDERS_MODE).toBe("live");
    expect(withMode("https://motionile.com", "").NEXT_PUBLIC_PROVIDERS_MODE).toBe("live");
    expect(withMode("https://motionile.com", "live").NEXT_PUBLIC_PROVIDERS_MODE).toBe("live");
  });

  it.each([
    "http://localhost:3000",
    "https://localhost:3443",
    "http://127.0.0.1:3000",
    "http://app.localhost:3000",
  ])("allows fake providers on the local site %s", (siteUrl) => {
    expect(withMode(siteUrl, "fake").NEXT_PUBLIC_PROVIDERS_MODE).toBe("fake");
  });

  it.each([
    "https://motionile.com",
    "https://staging.motionile.dev",
    "https://localhost.evil.example",
    "https://motionile.com/localhost",
  ])("rejects fake providers for the deployed site %s", (siteUrl) => {
    expect(() => withMode(siteUrl, "fake")).toThrow(/NEXT_PUBLIC_PROVIDERS_MODE/);
  });

  it("rejects unknown modes", () => {
    expect(() => withMode("http://localhost:3000", "sandbox")).toThrow(
      /NEXT_PUBLIC_PROVIDERS_MODE/,
    );
  });

  it("reports whether a url is a loopback address", () => {
    expect(isLoopbackUrl("http://localhost:3000")).toBe(true);
    expect(isLoopbackUrl("https://motionile.com")).toBe(false);
    expect(isLoopbackUrl("not a url")).toBe(false);
  });

  it("exposes the validated mode", () => {
    expect(env.NEXT_PUBLIC_PROVIDERS_MODE).toBe("live");
  });
});

describe("server env", () => {
  it("prefers the internal API url", () => {
    expect(parseServerEnv({ API_INTERNAL_URL: "http://api:8000/" }, env)).toEqual({
      apiBaseUrl: "http://api:8000",
    });
  });

  it("falls back to the public API url", () => {
    expect(parseServerEnv({ API_INTERNAL_URL: "" }, env)).toEqual({
      apiBaseUrl: env.NEXT_PUBLIC_API_URL,
    });
    expect(serverEnv.apiBaseUrl).toBe(DEFAULT_API_URL);
  });

  it("rejects an invalid internal url", () => {
    expect(() => parseServerEnv({ API_INTERNAL_URL: "not a url" }, env)).toThrow(
      /Invalid server environment variables/,
    );
  });
});
