import { describe, expect, it } from "vitest";

import { adminNavigation } from "@/config/navigation";
import { libraryKeys } from "@/features/library/query-keys";
import {
  isHttpsUrl,
  isPlayableRendition,
  playableRenditions,
} from "@/features/library/schemas/library.schema";
import { earliestExpiryMs, urlExpiryMs } from "@/features/library/url-expiry";

import { landscape, portrait, presignedUrl, rendition, square } from "./library-fixtures";

const SIGNED_AT = new Date("2026-10-20T10:00:00.000Z");

describe("url expiry", () => {
  it("reads the expiry of an S3 presigned url", () => {
    expect(urlExpiryMs(presignedUrl(SIGNED_AT, 900))).toBe(SIGNED_AT.getTime() + 900_000);
  });

  it("reads an epoch expiry parameter", () => {
    expect(urlExpiryMs("https://cdn.motionile.test/a.mp4?Expires=1790000000&Signature=x")).toBe(
      1_790_000_000_000,
    );
  });

  it("returns null for plain, malformed and empty urls", () => {
    expect(urlExpiryMs("https://cdn.motionile.test/a.mp4")).toBeNull();
    expect(urlExpiryMs("not a url")).toBeNull();
    expect(urlExpiryMs(null)).toBeNull();
    expect(urlExpiryMs(undefined)).toBeNull();
    expect(urlExpiryMs("http://localhost:9000/a?X-Amz-Date=garbage&X-Amz-Expires=900")).toBeNull();
    expect(urlExpiryMs(presignedUrl(SIGNED_AT, 0))).toBeNull();
  });

  it("takes the earliest expiry across every url of every rendition", () => {
    const items = [
      rendition({ url: presignedUrl(SIGNED_AT, 900), posterUrl: presignedUrl(SIGNED_AT, 300) }),
      rendition({ url: presignedUrl(SIGNED_AT, 600), posterUrl: null, subtitlesUrl: null }),
    ];

    expect(earliestExpiryMs(items)).toBe(SIGNED_AT.getTime() + 300_000);
    expect(earliestExpiryMs([landscape])).toBeNull();
    expect(earliestExpiryMs([])).toBeNull();
  });
});

describe("library schema helpers", () => {
  it("accepts only ready renditions with a url and orders them by aspect", () => {
    expect(isPlayableRendition(landscape)).toBe(true);
    expect(isPlayableRendition({ ...landscape, status: "failed" })).toBe(false);
    expect(isPlayableRendition({ ...landscape, url: null })).toBe(false);
    expect(isPlayableRendition({ ...landscape, url: "" })).toBe(false);
    expect(playableRenditions([square, { ...portrait, status: "pending" }, landscape])).toEqual([
      landscape,
      square,
    ]);
  });

  it("recognises https urls only", () => {
    expect(isHttpsUrl("https://example.com/l")).toBe(true);
    expect(isHttpsUrl("http://example.com/l")).toBe(false);
    expect(isHttpsUrl("javascript:alert(1)")).toBe(false);
    expect(isHttpsUrl("nope")).toBe(false);
  });

  it("nests query keys under the library root", () => {
    expect(libraryKeys.render("r1").slice(0, 2)).toEqual(libraryKeys.renders());
    expect(libraryKeys.renditions("r1")).not.toEqual(libraryKeys.render("r1"));
    expect(libraryKeys.mediaSession()).toEqual(["library", "media-session"]);
  });
});

describe("admin navigation", () => {
  it("links the music library behind the music.manage permission", () => {
    expect(adminNavigation.items).toContainEqual(
      expect.objectContaining({ title: "Music", href: "/admin/music", permission: "music.manage" }),
    );
  });
});
