import { ImageResponse } from "next/og";

import { brandPalette, siteConfig } from "@/config/site";
import { BrandMark, loadBrandFonts } from "@/lib/seo/brand-image";
import { OPEN_GRAPH_IMAGE_SIZE } from "@/lib/seo/metadata";

export async function catalogOpenGraph(title: string, eyebrow: string) {
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
        <div style={{ fontSize: 42, fontWeight: 600 }}>{siteConfig.name}</div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
        <div
          style={{
            fontFamily: "Geist Mono",
            fontSize: 22,
            letterSpacing: 4,
            textTransform: "uppercase",
            color: brandPalette.mutedText,
          }}
        >
          {eyebrow}
        </div>
        <div
          style={{
            maxWidth: 1000,
            fontSize: 68,
            fontWeight: 600,
            letterSpacing: -2,
            lineHeight: 1.08,
          }}
        >
          {title}
        </div>
      </div>
      <div style={{ fontSize: 24, color: brandPalette.secondaryText }}>
        Learn it clearly. Turn it into motion.
      </div>
    </div>,
    { ...OPEN_GRAPH_IMAGE_SIZE, fonts: [...fonts] },
  );
}
