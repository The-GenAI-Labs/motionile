import { describe, expect, it } from "vitest";

import { metadata, viewport } from "@/app/layout";
import robots from "@/app/robots";
import sitemap from "@/app/sitemap";

describe("seo", () => {
  it("lists only the home page in the sitemap", () => {
    expect(sitemap()).toEqual([
      { url: "https://motionile.test/", changeFrequency: "weekly", priority: 1 },
    ]);
  });

  it("blocks private areas and points crawlers to the sitemap", () => {
    expect(robots()).toEqual({
      rules: [{ userAgent: "*", allow: "/", disallow: ["/admin", "/api/"] }],
      sitemap: "https://motionile.test/sitemap.xml",
      host: "https://motionile.test",
    });
  });

  it("defines the title template, default title and metadata base", () => {
    expect(metadata.title).toEqual({
      default: "Motionile — AI Animated Explainer Videos",
      template: "%s · Motionile",
    });
    expect(metadata.metadataBase?.toString()).toBe("https://motionile.test/");
    expect(metadata.alternates?.canonical).toBe("/");
  });

  it("sets the dark theme color", () => {
    expect(viewport).toEqual({ themeColor: "#0E0E10", colorScheme: "dark" });
  });
});
