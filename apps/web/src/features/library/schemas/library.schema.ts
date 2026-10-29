import { z } from "zod";

import type {
  Aspect,
  JobSummary,
  LibraryFilters,
  PlayableRendition,
  Rendition,
} from "@/features/library/types/library.types";

export const renderIdSchema = z.uuid();

export const jobIdSchema = z.uuid();

export const LIBRARY_PAGE_SIZE = 24;
export const RECENT_VIDEOS_LIMIT = 6;
export const SEARCH_DEBOUNCE_MS = 300;
export const MAX_SEARCH_LENGTH = 100;

export const searchTextSchema = z.string().trim().min(1).max(MAX_SEARCH_LENGTH);

export const toLibraryFilters = (search: string, aspect: Aspect | null): LibraryFilters => {
  const q = searchTextSchema.safeParse(search);
  return {
    ...(q.success ? { q: q.data } : {}),
    ...(aspect === null ? {} : { aspect }),
  };
};

export const shareFormSchema = z.object({
  aspect: z.enum(["16:9", "9:16", "1:1"], "Choose which version to share."),
  allowIndexing: z.boolean(),
});

export type ShareFormValues = z.infer<typeof shareFormSchema>;

const ACTIVE_STATUSES = new Set<JobSummary["status"]>([
  "queued",
  "planning",
  "awaiting_approval",
  "voicing",
  "generating",
  "validating",
  "rendering",
]);

export const isActiveJob = (job: Pick<JobSummary, "status">): boolean =>
  ACTIVE_STATUSES.has(job.status);

export const jobStatusLabels = {
  queued: "Queued",
  planning: "Planning",
  awaiting_approval: "Waiting for your approval",
  voicing: "Recording narration",
  generating: "Building scenes",
  validating: "Checking the video",
  rendering: "Rendering",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
} as const satisfies Record<JobSummary["status"], string>;

export const jobPath = (jobId: string): `/jobs/${string}` => `/jobs/${jobId}`;

export const fallbackNotice = (count: number): string =>
  count === 1
    ? "1 scene uses a simplified layout"
    : `${String(count)} scenes use a simplified layout`;

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
