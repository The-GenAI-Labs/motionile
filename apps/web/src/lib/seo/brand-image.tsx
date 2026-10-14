import { readFile } from "node:fs/promises";
import { join } from "node:path";

import { brandPalette } from "@/config/site";

const GEIST_FONT_DIRECTORY = join(process.cwd(), "node_modules/geist/dist/fonts");

export const loadBrandFonts = async () => {
  const [regular, semiBold, mono] = await Promise.all([
    readFile(join(GEIST_FONT_DIRECTORY, "geist-sans/Geist-Regular.ttf")),
    readFile(join(GEIST_FONT_DIRECTORY, "geist-sans/Geist-SemiBold.ttf")),
    readFile(join(GEIST_FONT_DIRECTORY, "geist-mono/GeistMono-Regular.ttf")),
  ]);
  return [
    { name: "Geist", data: regular, weight: 400, style: "normal" },
    { name: "Geist", data: semiBold, weight: 600, style: "normal" },
    { name: "Geist Mono", data: mono, weight: 400, style: "normal" },
  ] as const;
};

interface BrandMarkProps {
  size: number;
}

export function BrandMark({ size }: BrandMarkProps) {
  return (
    <div
      style={{
        width: size,
        height: size,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        borderRadius: size * 0.22,
        background: brandPalette.accent,
        color: brandPalette.background,
        fontFamily: "Geist Mono",
        fontSize: size * 0.55,
      }}
    >
      M
    </div>
  );
}
