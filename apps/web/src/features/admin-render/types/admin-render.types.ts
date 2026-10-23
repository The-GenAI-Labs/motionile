import type {
  zAspect,
  zBedMusicTrackView,
  zGoldenCompositionView,
  zRenderBedView,
  zRenderStage,
  zRenderStatus,
  zRenderView,
  zRenditionView,
} from "@motionile/api-contract";
import type { z } from "zod";

export type Aspect = z.output<typeof zAspect>;
export type RenderBed = z.output<typeof zRenderBedView>;
export type CreatedRender = z.output<typeof zRenderView>;
export type RenderStatus = z.output<typeof zRenderStatus>;
export type RenderStage = z.output<typeof zRenderStage>;
export type BedRendition = z.output<typeof zRenditionView>;
export type BedMusicTrack = z.output<typeof zBedMusicTrackView>;
export type GoldenComposition = z.output<typeof zGoldenCompositionView>;

export type ConnectionState = "connecting" | "live" | "reconnecting" | "polling";
