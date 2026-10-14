import { describe, expect, it } from "vitest";

import {
  absoluteUrl,
  buildMetadata,
  defaultSocialImage,
  formatTitle,
  TITLE_TEMPLATE,
} from "@/lib/seo/metadata";

describe("absoluteUrl", () => {
  it("resolves paths against the site url", () => {
    expect(absoluteUrl("/")).toBe("https://motionile.test/");
    expect(absoluteUrl("/pricing")).toBe("https://motionile.test/pricing");
    expect(absoluteUrl("about")).toBe("https://motionile.test/about");
    expect(absoluteUrl("https://cdn.motionile.test/a.png")).toBe(
      "https://cdn.motionile.test/a.png",
    );
  });
});

describe("buildMetadata", () => {
  it("builds titles, canonical url, Open Graph and Twitter data consistently", () => {
    const metadata = buildMetadata({
      title: "Pricing",
      description: "How credits work.",
      path: "/pricing",
    });

    expect(metadata.title).toBe("Pricing");
    expect(metadata.description).toBe("How credits work.");
    expect(metadata.alternates?.canonical).toBe("https://motionile.test/pricing");
    expect(metadata.openGraph).toEqual({
      type: "website",
      siteName: "Motionile",
      locale: "en_IN",
      url: "https://motionile.test/pricing",
      title: "Pricing · Motionile",
      description: "How credits work.",
      images: [defaultSocialImage()],
    });
    expect(metadata.twitter).toEqual({
      card: "summary_large_image",
      title: "Pricing · Motionile",
      description: "How credits work.",
      images: [defaultSocialImage()],
    });
    expect(metadata.robots).toEqual({ index: true, follow: true });
  });

  it("uses the absolute default title when no title is given", () => {
    const metadata = buildMetadata({ description: "Home", path: "/" });

    expect(metadata.title).toEqual({ absolute: "Motionile — AI Animated Explainer Videos" });
    expect(metadata.openGraph?.title).toBe("Motionile — AI Animated Explainer Videos");
    expect(metadata.alternates?.canonical).toBe("https://motionile.test/");
  });

  it("supports noIndex, custom types and custom images", () => {
    const metadata = buildMetadata({
      title: "Video",
      description: "A video",
      path: "/v/abc",
      noIndex: true,
      openGraphType: "video.other",
      images: [{ url: "/v/abc/thumbnail.png", width: 1280, height: 720, alt: "Thumbnail" }],
    });

    expect(metadata.robots).toEqual({ index: false, follow: false });
    expect(metadata.openGraph).toMatchObject({
      type: "video.other",
      images: [
        {
          url: "https://motionile.test/v/abc/thumbnail.png",
          width: 1280,
          height: 720,
          alt: "Thumbnail",
        },
      ],
    });
  });

  it("formats titles with the template", () => {
    expect(TITLE_TEMPLATE).toBe("%s · Motionile");
    expect(formatTitle("About")).toBe("About · Motionile");
    expect(defaultSocialImage()).toEqual({
      url: "https://motionile.test/opengraph-image",
      width: 1200,
      height: 630,
      alt: "Motionile: Turn any topic into a narrated, animated explainer video.",
    });
  });
});
