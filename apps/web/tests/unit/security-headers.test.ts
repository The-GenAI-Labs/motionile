import { describe, expect, it } from "vitest";

import {
  ALL_ROUTES_SOURCE,
  buildContentSecurityPolicy,
  buildCspDirectives,
  buildHeaderRules,
  buildPermissionsPolicy,
  buildSecurityHeaders,
  PERMISSIONS_POLICY,
  serializeCsp,
  STRICT_TRANSPORT_SECURITY,
  VOICES_PERMISSIONS_POLICY,
  VOICES_ROUTE_SOURCE,
} from "@/config/security-headers";

const production = {
  isDevelopment: false,
  siteUrl: "https://motionile.com",
  apiUrl: "https://api.motionile.com/",
  cdnUrl: "https://cdn.motionile.com/videos",
  mediaOrigin: "https://storage.motionile.com",
};

const development = {
  isDevelopment: true,
  siteUrl: "http://localhost:3000",
  apiUrl: "http://localhost:8000",
};

const headerValue = (headers: { key: string; value: string }[], key: string) =>
  headers.find((header) => header.key === key)?.value;

describe("content security policy", () => {
  it("builds a strict production policy", () => {
    const directives = buildCspDirectives(production);

    expect(directives["default-src"]).toEqual(["'self'"]);
    expect(directives["script-src"]).toEqual([
      "'self'",
      "'unsafe-inline'",
      "https://challenges.cloudflare.com",
      "https://checkout.razorpay.com",
    ]);
    expect(directives["style-src"]).toEqual(["'self'", "'unsafe-inline'"]);
    expect(directives["img-src"]).toEqual([
      "'self'",
      "data:",
      "https://cdn.motionile.com",
      "https://storage.motionile.com",
    ]);
    expect(directives["media-src"]).toEqual([
      "'self'",
      "blob:",
      "https://cdn.motionile.com",
      "https://storage.motionile.com",
    ]);
    expect(directives["font-src"]).toEqual(["'self'"]);
    expect(directives["connect-src"]).toEqual([
      "'self'",
      "https://api.motionile.com",
      "https://api.razorpay.com",
    ]);
    expect(directives["frame-src"]).toEqual([
      "https://challenges.cloudflare.com",
      "https://api.razorpay.com",
      "https://checkout.razorpay.com",
    ]);
    expect(directives["frame-ancestors"]).toEqual(["'none'"]);
    expect(directives["object-src"]).toEqual(["'none'"]);
    expect(directives["base-uri"]).toEqual(["'self'"]);
    expect(directives["form-action"]).toEqual(["'self'"]);
    expect(directives["upgrade-insecure-requests"]).toEqual([]);
  });

  it("allows exactly the Razorpay Checkout origins and no wildcards", () => {
    const directives = buildCspDirectives(production);

    expect(directives["script-src"]).toContain("https://checkout.razorpay.com");
    expect(directives["frame-src"]).toEqual(
      expect.arrayContaining(["https://api.razorpay.com", "https://checkout.razorpay.com"]),
    );
    expect(directives["connect-src"]).toContain("https://api.razorpay.com");
    expect(
      Object.entries(directives)
        .filter(([name]) => name !== "default-src")
        .flatMap(([, sources]) => sources)
        .filter((source) => source.includes("razorpay")),
    ).toEqual([
      "https://checkout.razorpay.com",
      "https://api.razorpay.com",
      "https://api.razorpay.com",
      "https://checkout.razorpay.com",
    ]);
    expect(buildContentSecurityPolicy(production)).not.toContain("*");
  });

  it("does not allow Razorpay as a media, image, font or object source", () => {
    const directives = buildCspDirectives(production);

    for (const name of [
      "img-src",
      "media-src",
      "font-src",
      "object-src",
      "style-src",
      "default-src",
    ]) {
      expect(directives[name]?.some((source) => source.includes("razorpay"))).toBe(false);
    }
  });

  it("allows the CDN and storage origins as media and poster sources", () => {
    const directives = buildCspDirectives(production);

    for (const name of ["media-src", "img-src"]) {
      expect(directives[name]).toEqual(
        expect.arrayContaining(["https://cdn.motionile.com", "https://storage.motionile.com"]),
      );
    }
    expect(directives["connect-src"]).not.toContain("https://cdn.motionile.com");
    expect(directives["connect-src"]).not.toContain("https://storage.motionile.com");
  });

  it("allows blob: only as a media source so recordings can be played back", () => {
    for (const options of [production, development]) {
      const directives = buildCspDirectives(options);

      expect(directives["media-src"]).toContain("blob:");
      expect(
        Object.entries(directives)
          .filter(([, sources]) => sources.some((source) => source.startsWith("blob:")))
          .map(([name]) => name),
      ).toEqual(["media-src"]);
    }
    expect(buildContentSecurityPolicy(production)).toMatch(/media-src [^;]*blob:/);
    expect(buildContentSecurityPolicy(production)).not.toMatch(
      /(img|connect|script|default)-src [^;]*blob:/,
    );
  });

  it("keeps media-src to self and blob when no media origin is configured", () => {
    const directives = buildCspDirectives({
      isDevelopment: false,
      siteUrl: production.siteUrl,
      apiUrl: production.apiUrl,
    });

    expect(directives["media-src"]).toEqual(["'self'", "blob:"]);
    expect(directives["img-src"]).toEqual(["'self'", "data:"]);
  });

  it("deduplicates a media origin that equals the CDN origin", () => {
    const directives = buildCspDirectives({
      ...production,
      mediaOrigin: "https://cdn.motionile.com",
    });

    expect(directives["media-src"]).toEqual(["'self'", "blob:", "https://cdn.motionile.com"]);
  });

  it("allows a local storage origin over http in development", () => {
    const policy = buildContentSecurityPolicy({
      ...development,
      mediaOrigin: "http://localhost:9000",
    });

    expect(policy).toContain("media-src 'self' blob: http://localhost:9000;");
    expect(policy).toContain("img-src 'self' data: http://localhost:9000;");
  });

  it("never allows unsafe-eval in production", () => {
    expect(buildContentSecurityPolicy(production)).not.toContain("unsafe-eval");
  });

  it("allows unsafe-eval only in development and skips the upgrade directive", () => {
    const policy = buildContentSecurityPolicy(development);

    expect(policy).toContain("script-src 'self' 'unsafe-inline' 'unsafe-eval'");
    expect(policy).not.toContain("upgrade-insecure-requests");
    expect(policy).toContain("img-src 'self' data:;");
  });

  it("does not upgrade requests for a plain http production site", () => {
    expect(
      buildContentSecurityPolicy({ ...production, siteUrl: "http://localhost:3000" }),
    ).not.toContain("upgrade-insecure-requests");
  });

  it("serializes directives in order", () => {
    expect(serializeCsp({ "default-src": ["'self'"], "upgrade-insecure-requests": [] })).toBe(
      "default-src 'self'; upgrade-insecure-requests",
    );
    expect(buildContentSecurityPolicy(production)).toMatch(
      /^default-src 'self'; script-src .+; form-action 'self'; upgrade-insecure-requests$/,
    );
  });
});

describe("security headers", () => {
  it("sends every production header", () => {
    const headers = buildSecurityHeaders(production);

    expect(headers.map((header) => header.key)).toEqual([
      "Content-Security-Policy",
      "Referrer-Policy",
      "X-Content-Type-Options",
      "X-Frame-Options",
      "Permissions-Policy",
      "Strict-Transport-Security",
    ]);
    expect(headerValue(headers, "Referrer-Policy")).toBe("strict-origin-when-cross-origin");
    expect(headerValue(headers, "X-Content-Type-Options")).toBe("nosniff");
    expect(headerValue(headers, "X-Frame-Options")).toBe("DENY");
    expect(headerValue(headers, "Strict-Transport-Security")).toBe(STRICT_TRANSPORT_SECURITY);
    expect(STRICT_TRANSPORT_SECURITY).toBe("max-age=63072000; includeSubDomains; preload");
  });

  it("restricts powerful browser features", () => {
    expect(PERMISSIONS_POLICY).toContain("camera=()");
    expect(PERMISSIONS_POLICY).toContain("microphone=()");
    expect(PERMISSIONS_POLICY).not.toContain("microphone=(self)");
    expect(PERMISSIONS_POLICY).toContain("geolocation=()");
    expect(PERMISSIONS_POLICY).toContain(
      'payment=(self "https://checkout.razorpay.com" "https://api.razorpay.com")',
    );
  });

  it("omits HSTS in development", () => {
    expect(
      buildSecurityHeaders(development).some(
        (header) => header.key === "Strict-Transport-Security",
      ),
    ).toBe(false);
  });
});

describe("permissions policy scope", () => {
  const microphoneDirective = (value: string) => /microphone=\([^)]*\)/.exec(value)?.[0];

  it("denies the microphone by default and allows it only for the voices route", () => {
    expect(microphoneDirective(PERMISSIONS_POLICY)).toBe("microphone=()");
    expect(microphoneDirective(VOICES_PERMISSIONS_POLICY)).toBe("microphone=(self)");
    expect(buildPermissionsPolicy("none")).toBe(PERMISSIONS_POLICY);
    expect(buildPermissionsPolicy("self")).toBe(VOICES_PERMISSIONS_POLICY);
  });

  it("differs between the default and the voices policy only by the microphone", () => {
    expect(VOICES_PERMISSIONS_POLICY.replace("microphone=(self)", "microphone=()")).toBe(
      PERMISSIONS_POLICY,
    );
  });

  it("allows the microphone for exactly one route rule and keeps every other header unchanged", () => {
    const rules = buildHeaderRules(production);
    const microphoneAllowed = rules.filter((rule) =>
      rule.headers.some(
        (header) =>
          header.key === "Permissions-Policy" &&
          microphoneDirective(header.value) !== "microphone=()",
      ),
    );

    expect(rules.map((rule) => rule.source)).toEqual([ALL_ROUTES_SOURCE, VOICES_ROUTE_SOURCE]);
    expect(microphoneAllowed.map((rule) => rule.source)).toEqual([VOICES_ROUTE_SOURCE]);
    expect(VOICES_ROUTE_SOURCE).toBe("/settings/voices/:path*");
    expect(rules[1]?.headers).toEqual([
      { key: "Permissions-Policy", value: VOICES_PERMISSIONS_POLICY },
    ]);
    expect(headerValue(rules[0]?.headers ?? [], "Permissions-Policy")).toBe(PERMISSIONS_POLICY);
  });

  it("never allows the microphone for the whole site or through a wildcard", () => {
    for (const options of [production, development]) {
      const [global] = buildHeaderRules(options);
      const value = headerValue(global?.headers ?? [], "Permissions-Policy") ?? "";

      expect(value).toContain("microphone=()");
      expect(value).not.toMatch(/microphone=\([^)]*(self|\*)/);
    }
    expect(VOICES_PERMISSIONS_POLICY).not.toContain("*");
    expect(VOICES_PERMISSIONS_POLICY).not.toMatch(/microphone=\([^)]*"/);
  });

  it("never emits a wildcard in any header", () => {
    for (const options of [production, development]) {
      for (const rule of buildHeaderRules(options)) {
        for (const header of rule.headers) {
          expect(header.value).not.toContain("*");
        }
      }
    }
  });
});
