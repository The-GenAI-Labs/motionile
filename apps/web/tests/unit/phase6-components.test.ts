import { describe, expect, it } from "vitest";

import { reorderCatalogItems } from "@/features/catalog/components/catalog-tree";
import { seoLengthState } from "@/features/catalog/components/seo-preview";
import { validateSettingValue } from "@/features/platform/schemas/settings.schema";
import { AVATAR_MAX_BYTES, avatarFileError } from "@/features/users/components/avatar-upload";

describe("Phase 6 component rules", () => {
  it("reorders catalog entries without mutating the source", () => {
    const entries = [
      { id: "a", title: "Alpha", kind: "category" as const, active: true },
      { id: "b", title: "Beta", kind: "category" as const, active: true },
      { id: "c", title: "Gamma", kind: "category" as const, active: false },
    ];
    expect(reorderCatalogItems(entries, "c", "a").map((entry) => entry.id)).toEqual([
      "c",
      "a",
      "b",
    ]);
    expect(entries.map((entry) => entry.id)).toEqual(["a", "b", "c"]);
  });

  it("reports SEO field length states", () => {
    expect(seoLengthState("", 60)).toBe("empty");
    expect(seoLengthState("Clear title", 60)).toBe("good");
    expect(seoLengthState("x".repeat(61), 60)).toBe("long");
  });

  it("validates schema-driven setting bounds and types", () => {
    const schema = { type: "integer" as const, minimum: 6, maximum: 100 };
    expect(validateSettingValue(schema, 24)).toBe(true);
    expect(validateSettingValue(schema, 5)).toBe(false);
    expect(validateSettingValue(schema, 12.5)).toBe(false);
  });

  it("rejects oversized and unsupported avatar files", () => {
    expect(
      avatarFileError(
        new File([new Uint8Array(AVATAR_MAX_BYTES + 1)], "large.png", { type: "image/png" }),
      ),
    ).toMatch(/smaller/);
    expect(avatarFileError(new File(["image"], "avatar.svg", { type: "image/svg+xml" }))).toMatch(
      /JPEG/,
    );
    expect(avatarFileError(new File(["image"], "avatar.webp", { type: "image/webp" }))).toBeNull();
  });
});
