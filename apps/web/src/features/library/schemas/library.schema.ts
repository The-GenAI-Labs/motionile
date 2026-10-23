import { z } from "zod";

import type { Aspect, PlayableRendition, Rendition } from "@/features/library/types/library.types";

export const renderIdSchema = z.uuid();

export const ASPECT_ORDER = ["16:9", "9:16", "1:1"] as const satisfies readonly Aspect[];

export const aspectLabels = {
  "16:9": "16:9",
  "9:16": "9:16",
  "1:1": "1:1",
} as const satisfies Record<Aspect, string>;

export const aspectDescriptions = {
  "16:9": "Landscape",
  "9:16": "Portrait",
  "1:1": "Square",
} as const satisfies Record<Aspect, string>;

export const isPlayableRendition = (rendition: Rendition): rendition is PlayableRendition =>
  rendition.status === "ready" && typeof rendition.url === "string" && rendition.url !== "";

export const playableRenditions = (renditions: readonly Rendition[]): PlayableRendition[] =>
  renditions
    .filter(isPlayableRendition)
    .toSorted((a, b) => ASPECT_ORDER.indexOf(a.aspect) - ASPECT_ORDER.indexOf(b.aspect));

export const isHttpsUrl = (value: string): boolean =>
  URL.canParse(value) && new URL(value).protocol === "https:";
