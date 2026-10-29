import type { CSSProperties } from "react";

import type { StyleOption } from "@/features/generation/types/generation.types";

const SAFE_COLOR =
  /^(#[0-9a-fA-F]{3,8}|[a-zA-Z]+|(rgb|hsl|oklch|oklab|lab|lch|color)a?\([0-9a-zA-Z\s.,%/+-]{1,80}\))$/;

export const safeColor = (value: string): string | undefined =>
  SAFE_COLOR.test(value.trim()) ? value.trim() : undefined;

type SwatchProperties = CSSProperties & Record<`--${string}`, string | undefined>;

export const swatchProperties = (style: StyleOption): SwatchProperties => ({
  "--swatch-background": safeColor(style.background),
  "--swatch-surface": safeColor(style.surface),
  "--swatch-text": safeColor(style.text),
  "--swatch-accent": safeColor(style.accent),
});

export function StyleSwatch({ style }: { style: StyleOption }) {
  return (
    <span
      aria-hidden="true"
      data-testid="style-swatch"
      style={swatchProperties(style)}
      className="flex h-20 w-full flex-col justify-between rounded-md border bg-(--swatch-background) p-2"
    >
      <span className="block h-2 w-2/3 rounded-full bg-(--swatch-text)" />
      <span className="flex items-end justify-between gap-2">
        <span className="block h-7 w-2/3 rounded-sm bg-(--swatch-surface)" />
        <span className="block size-4 rounded-full bg-(--swatch-accent)" />
      </span>
    </span>
  );
}
