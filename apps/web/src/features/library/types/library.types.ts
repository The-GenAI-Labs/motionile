import type {
  zAspect,
  zMediaDeliveryMode,
  zMediaSessionView,
  zMusicAttributionView,
  zRenderView,
  zRenditionView,
} from "@motionile/api-contract";
import type { z } from "zod";

export type Aspect = z.output<typeof zAspect>;
export type MediaDeliveryMode = z.output<typeof zMediaDeliveryMode>;
export type MediaSession = z.output<typeof zMediaSessionView>;
export type MusicAttribution = z.output<typeof zMusicAttributionView>;
export type Render = z.output<typeof zRenderView>;
export type Rendition = z.output<typeof zRenditionView>;

export type PlayableRendition = Rendition & { url: string };
