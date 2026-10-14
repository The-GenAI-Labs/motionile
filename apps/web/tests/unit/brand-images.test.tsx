import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Icon, { contentType as iconContentType, size as iconSize } from "@/app/icon";
import OpenGraphImage, { alt, contentType, size } from "@/app/opengraph-image";
import { BrandMark, loadBrandFonts } from "@/lib/seo/brand-image";

describe("brand images", () => {
  it("loads the Geist fonts used by generated images", async () => {
    const fonts = await loadBrandFonts();

    expect(fonts.map((font) => `${font.name} ${String(font.weight)}`)).toEqual([
      "Geist 400",
      "Geist 600",
      "Geist Mono 400",
    ]);
    for (const font of fonts) {
      expect(font.data.byteLength).toBeGreaterThan(0);
    }
  });

  it("renders the brand mark", () => {
    render(<BrandMark size={64} />);

    expect(screen.getByText("M")).toBeInTheDocument();
  });

  it("describes the Open Graph image", async () => {
    expect(alt).toBe("Motionile: Turn any topic into a narrated, animated explainer video.");
    expect(size).toEqual({ width: 1200, height: 630 });
    expect(contentType).toBe("image/png");

    const response = await OpenGraphImage();
    expect(response.headers.get("content-type")).toBe("image/png");
  });

  it("describes the app icon", async () => {
    expect(iconSize).toEqual({ width: 512, height: 512 });
    expect(iconContentType).toBe("image/png");

    const response = await Icon();
    expect(response.headers.get("content-type")).toBe("image/png");
  });
});
