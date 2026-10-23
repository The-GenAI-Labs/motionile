import type { zMusicTrackView } from "@motionile/api-contract";
import type { z } from "zod";

export type MusicTrack = z.output<typeof zMusicTrackView>;

export interface MusicFilters {
  mood?: string;
  active?: boolean;
}

export interface MusicUploadMetadata {
  title: string;
  mood: string;
  bpm?: number;
  licenseName: string;
  licenseUrl: string;
  attributionText?: string;
  activate: boolean;
}

export interface MusicUploadInput {
  file: File;
  metadata: MusicUploadMetadata;
}

export interface MusicUpdateInput {
  title?: string;
  mood?: string;
  bpm?: number | null;
  licenseName?: string;
  licenseUrl?: string;
  attributionText?: string | null;
}

export type MusicActiveAction = "activate" | "deactivate";
