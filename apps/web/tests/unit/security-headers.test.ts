import { describe, expect, it } from "vitest";

import {
  buildContentSecurityPolicy,
  buildCspDirectives,
  buildSecurityHeaders,
  PERMISSIONS_POLICY,
  serializeCsp,
  STRICT_TRANSPORT_SECURITY,
} from "@/config/security-headers";

const production = {
  isDevelopment: false,
  siteUrl: "https://motionile.com",
  apiUrl: "https://api.motionile.com/",
  cdnUrl: "https://cdn.motionile.com/videos",
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
    expect(directives["img-src"]).toEqual(["'self'", "data:", "https://cdn.motionile.com"]);
    expect(directives["media-src"]).toEqual(["'self'", "https://cdn.motionile.com"]);
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
    expect(PERMISSIONS_POLICY).toContain("microphone=(self)");
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
