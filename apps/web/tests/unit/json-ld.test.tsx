import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  buildBreadcrumbListJsonLd,
  buildOrganizationJsonLd,
  buildSoftwareApplicationJsonLd,
  buildVideoObjectJsonLd,
  JsonLd,
  serializeJsonLd,
  toIsoDuration,
} from "@/lib/seo/json-ld";

describe("serializeJsonLd", () => {
  it("escapes characters that could break out of a script element", () => {
    const serialized = serializeJsonLd({
      ...buildOrganizationJsonLd(),
      name: "</script><script>alert(1)</script> & \u2028 \u2029",
    });

    expect(serialized).not.toMatch(/[<>&\u2028\u2029]/);
    expect(serialized).toContain("\\u003c/script\\u003e");
    expect(serialized).toContain("\\u0026");
    expect(serialized).toContain("\\u2028");
    expect(serialized).toContain("\\u2029");
    expect(JSON.parse(serialized)).toMatchObject({
      name: "</script><script>alert(1)</script> & \u2028 \u2029",
    });
  });
});

describe("JsonLd", () => {
  it("renders an inert JSON-LD script", () => {
    const { container } = render(<JsonLd data={[buildOrganizationJsonLd()]} />);
    const script = container.querySelector('script[type="application/ld+json"]');

    expect(JSON.parse(script?.textContent ?? "null")).toEqual([buildOrganizationJsonLd()]);
  });
});

describe("builders", () => {
  it("describes the organization", () => {
    expect(buildOrganizationJsonLd()).toEqual({
      "@context": "https://schema.org",
      "@type": "Organization",
      name: "Motionile",
      url: "https://motionile.test/",
      logo: "https://motionile.test/icon",
      description: expect.any(String) as string,
      email: "support@motionile.com",
      sameAs: [
        "https://www.youtube.com/@motionile",
        "https://www.linkedin.com/company/motionile",
        "https://x.com/motionile",
      ],
    });
  });

  it("describes the software application", () => {
    expect(buildSoftwareApplicationJsonLd()).toMatchObject({
      "@type": "SoftwareApplication",
      name: "Motionile",
      applicationCategory: "MultimediaApplication",
      operatingSystem: "Web",
      publisher: { "@type": "Organization", name: "Motionile" },
    });
  });

  it("numbers breadcrumb items from one with absolute urls", () => {
    expect(
      buildBreadcrumbListJsonLd([
        { name: "Explore", path: "/explore" },
        { name: "Tech", path: "/explore/tech" },
      ]),
    ).toEqual({
      "@context": "https://schema.org",
      "@type": "BreadcrumbList",
      itemListElement: [
        {
          "@type": "ListItem",
          position: 1,
          name: "Explore",
          item: "https://motionile.test/explore",
        },
        {
          "@type": "ListItem",
          position: 2,
          name: "Tech",
          item: "https://motionile.test/explore/tech",
        },
      ],
    });
  });

  it("describes a video with an ISO 8601 duration", () => {
    expect(
      buildVideoObjectJsonLd({
        name: "How DNS works",
        description: "DNS explained",
        path: "/v/abc",
        thumbnailUrls: ["/v/abc/thumb.png", "https://cdn.motionile.test/t.png"],
        uploadDate: new Date("2026-10-01T10:00:00Z"),
        durationSeconds: 95,
        contentUrl: "https://cdn.motionile.test/v.mp4",
        embedUrl: "/v/abc/embed",
      }),
    ).toEqual({
      "@context": "https://schema.org",
      "@type": "VideoObject",
      name: "How DNS works",
      description: "DNS explained",
      url: "https://motionile.test/v/abc",
      thumbnailUrl: ["https://motionile.test/v/abc/thumb.png", "https://cdn.motionile.test/t.png"],
      uploadDate: "2026-10-01T10:00:00.000Z",
      duration: "PT1M35S",
      contentUrl: "https://cdn.motionile.test/v.mp4",
      embedUrl: "https://motionile.test/v/abc/embed",
      publisher: { "@type": "Organization", name: "Motionile", url: "https://motionile.test/" },
    });
  });

  it("omits optional video urls and keeps string dates", () => {
    const video = buildVideoObjectJsonLd({
      name: "A",
      description: "B",
      path: "/v/a",
      thumbnailUrls: [],
      uploadDate: "2026-10-01",
      durationSeconds: 10,
    });

    expect(video.uploadDate).toBe("2026-10-01");
    expect(video).not.toHaveProperty("contentUrl");
    expect(video).not.toHaveProperty("embedUrl");
  });

  it.each([
    [0, "PT0S"],
    [10, "PT10S"],
    [60, "PT1M"],
    [120, "PT2M"],
    [3_725, "PT1H2M5S"],
    [-5, "PT0S"],
  ])("formats %d seconds as %s", (seconds, expected) => {
    expect(toIsoDuration(seconds)).toBe(expected);
  });
});
