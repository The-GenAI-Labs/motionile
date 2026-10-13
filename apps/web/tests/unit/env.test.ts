import { describe, expect, it } from "vitest";

import { env } from "@/config/env";
import {
  DEFAULT_API_URL,
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
