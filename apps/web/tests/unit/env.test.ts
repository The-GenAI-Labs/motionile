import { describe, expect, it } from "vitest";

import { env } from "@/config/env";
import { parsePublicEnv, readPublicEnv } from "@/config/env-schema";

describe("public env", () => {
  it("accepts an https site url and strips trailing slashes", () => {
    expect(parsePublicEnv({ NEXT_PUBLIC_SITE_URL: "https://motionile.com/" })).toEqual({
      NEXT_PUBLIC_SITE_URL: "https://motionile.com",
    });
  });

  it("accepts a local http url", () => {
    expect(
      parsePublicEnv({ NEXT_PUBLIC_SITE_URL: "http://localhost:3000" }).NEXT_PUBLIC_SITE_URL,
    ).toBe("http://localhost:3000");
  });

  it("rejects a missing site url", () => {
    expect(() => parsePublicEnv({})).toThrow(/NEXT_PUBLIC_SITE_URL/);
  });

  it("rejects a non-http url", () => {
    expect(() => parsePublicEnv({ NEXT_PUBLIC_SITE_URL: "ftp://motionile.com" })).toThrow(
      /Invalid public environment variables/,
    );
  });

  it("exposes the validated environment", () => {
    expect(env.NEXT_PUBLIC_SITE_URL).toBe("https://motionile.test");
    expect(readPublicEnv()).toEqual(env);
  });
});
