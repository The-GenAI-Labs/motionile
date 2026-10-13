import { ImageResponse } from "next/og";

import { brandPalette, siteConfig } from "@/config/site";
import { BrandMark, loadBrandFonts } from "@/lib/seo/brand-image";
import { OPEN_GRAPH_IMAGE_ALT, OPEN_GRAPH_IMAGE_SIZE } from "@/lib/seo/metadata";

export const alt = OPEN_GRAPH_IMAGE_ALT;
export const size = OPEN_GRAPH_IMAGE_SIZE;
export const contentType = "image/png";

export default async function OpenGraphImage() {
  const fonts = await loadBrandFonts();
  return new ImageResponse(
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        padding: 80,
        background: brandPalette.background,
        color: brandPalette.text,
        fontFamily: "Geist",
        border: `1px solid ${brandPalette.border}`,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 24 }}>
        <BrandMark size={72} />
        <div style={{ fontSize: 44, fontWeight: 600, letterSpacing: -1 }}>{siteConfig.name}</div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
        <div
          style={{
            fontFamily: "Geist Mono",
            fontSize: 22,
            letterSpacing: 4,
            textTransform: "uppercase",
            color: brandPalette.mutedText,
          }}
        >
          AI animated explainer videos
        </div>
        <div style={{ fontSize: 68, fontWeight: 600, letterSpacing: -2, lineHeight: 1.1 }}>
          {siteConfig.tagline}
        </div>
      </div>
      <div
        style={{
          display: "flex",
          gap: 16,
          fontSize: 26,
          color: brandPalette.secondaryText,
        }}
      >
        Topic → Storyboard → Narration → Video
      </div>
    </div>,
    { ...size, fonts: [...fonts] },
  );
}
