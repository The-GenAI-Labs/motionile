import { ImageResponse } from "next/og";

import { brandPalette } from "@/config/site";
import { BrandMark, loadBrandFonts } from "@/lib/seo/brand-image";

export const size = { width: 512, height: 512 };
export const contentType = "image/png";

export default async function Icon() {
  const fonts = await loadBrandFonts();
  return new ImageResponse(
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: brandPalette.background,
      }}
    >
      <BrandMark size={400} />
    </div>,
    { ...size, fonts: [...fonts] },
  );
}
