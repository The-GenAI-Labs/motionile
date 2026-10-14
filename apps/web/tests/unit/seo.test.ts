import { describe, expect, it } from "vitest";

import { metadata, viewport } from "@/app/layout";
import robots from "@/app/robots";
import sitemap from "@/app/sitemap";

describe("sitemap", () => {
  it("lists every public page with absolute urls", () => {
    expect(sitemap()).toEqual([
      { url: "https://motionile.test/", changeFrequency: "weekly", priority: 1 },
      { url: "https://motionile.test/pricing", changeFrequency: "monthly", priority: 0.8 },
      { url: "https://motionile.test/about", changeFrequency: "monthly", priority: 0.6 },
      { url: "https://motionile.test/contact", changeFrequency: "yearly", priority: 0.5 },
      { url: "https://motionile.test/legal/terms", changeFrequency: "yearly", priority: 0.3 },
      { url: "https://motionile.test/legal/privacy", changeFrequency: "yearly", priority: 0.3 },
      {
        url: "https://motionile.test/legal/refund-policy",
        changeFrequency: "yearly",
        priority: 0.3,
      },
      {
        url: "https://motionile.test/legal/data-deletion",
        changeFrequency: "yearly",
        priority: 0.3,
      },
    ]);
  });
});

describe("robots", () => {
  it("blocks the admin console, the user area, auth pages and the API", () => {
    const result = robots();
    const rules = Array.isArray(result.rules) ? result.rules : [result.rules];

    expect(rules).toHaveLength(1);
    expect(rules[0]?.userAgent).toBe("*");
    expect(rules[0]?.allow).toBe("/");
    expect(rules[0]?.disallow).toEqual(
      expect.arrayContaining([
        "/admin",
        "/api/",
        "/dashboard",
        "/create",
        "/library",
        "/publications",
        "/skills",
        "/billing",
        "/settings",
        "/jobs",
        "/publish",
        "/login",
        "/register",
        "/verify",
        "/forgot-password",
        "/reset-password",
        "/refresh",
      ]),
    );
    expect(result.sitemap).toBe("https://motionile.test/sitemap.xml");
    expect(result.host).toBe("https://motionile.test");
  });

  it("never blocks a public page", () => {
    const disallowed = [robots().rules].flat().flatMap((rule) => [rule.disallow ?? []].flat());

    for (const { url } of sitemap()) {
      const path = new URL(url).pathname;
      expect(disallowed.some((prefix) => path.startsWith(prefix))).toBe(false);
    }
  });
});

describe("root metadata", () => {
  it("defines the title template, default title and metadata base", () => {
    expect(metadata.title).toEqual({
      default: "Motionile — AI Animated Explainer Videos",
      template: "%s · Motionile",
    });
    expect(metadata.metadataBase?.toString()).toBe("https://motionile.test/");
    expect(metadata.alternates?.canonical).toBe("https://motionile.test/");
    expect(metadata.applicationName).toBe("Motionile");
  });

  it("sets the dark theme color", () => {
    expect(viewport).toEqual({ themeColor: "#0E0E10", colorScheme: "dark" });
  });
});
