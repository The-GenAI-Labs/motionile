import type {
  zAdminVoiceView,
  zCloneAttemptView,
  zCloneLimitsView,
  zCloneSampleView,
  zCloneStartView,
  zVoiceKind,
  zVoicePreviewView,
  zVoiceStatus,
  zVoiceView,
} from "@motionile/api-contract";
import type { z } from "zod";

export type Voice = z.output<typeof zVoiceView>;
export type AdminVoice = z.output<typeof zAdminVoiceView>;
export type VoiceKind = z.output<typeof zVoiceKind>;
export type VoiceStatus = z.output<typeof zVoiceStatus>;
export type VoicePreview = z.output<typeof zVoicePreviewView>;
export type CloneStart = z.output<typeof zCloneStartView>;
export type CloneAttempt = z.output<typeof zCloneAttemptView>;
export type CloneLimits = z.output<typeof zCloneLimitsView>;
export type CloneSample = z.output<typeof zCloneSampleView>;

export interface VoiceFilters {
  language?: string;
  kind?: VoiceKind;
}

export interface CloneSubmitInput {
  name: string;
  language: string;
  idempotencyKey: string;
}

export interface AudioUploadInput {
  attemptId: string;
  file: Blob;
  filename: string;
}
