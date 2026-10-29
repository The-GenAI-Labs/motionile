import type {
  zAspect,
  zJobView,
  zLibraryItem,
  zMediaDeliveryMode,
  zMediaSessionView,
  zMusicAttributionView,
  zRenderView,
  zRenditionView,
  zSharedVideoView,
  zShareLinkView,
} from "@motionile/api-contract";
import type { z } from "zod";

export type Aspect = z.output<typeof zAspect>;
export type MediaDeliveryMode = z.output<typeof zMediaDeliveryMode>;
export type MediaSession = z.output<typeof zMediaSessionView>;
export type MusicAttribution = z.output<typeof zMusicAttributionView>;
export type Render = z.output<typeof zRenderView>;
export type Rendition = z.output<typeof zRenditionView>;
export type LibraryItem = z.output<typeof zLibraryItem>;
export type ShareLink = z.output<typeof zShareLinkView>;
export type SharedVideo = z.output<typeof zSharedVideoView>;
export type JobSummary = z.output<typeof zJobView>;

export interface LibraryFilters {
  q?: string;
  aspect?: Aspect;
}

export interface ShareInput {
  aspect: Aspect;
  allowIndexing: boolean;
}

export type PlayableRendition = Rendition & { url: string };
