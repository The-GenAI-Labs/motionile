import type {
  zAspectName,
  zEstimateView,
  zJobPage,
  zJobStatus,
  zJobView,
  zShareLinkView,
  zStoryboard,
  zStoryboardIssue,
  zStoryboardLimitsView,
  zStoryboardScene,
  zStoryboardView,
  zStyleView,
} from "@motionile/api-contract";
import type { z } from "zod";

export type Aspect = z.output<typeof zAspectName>;
export type Job = z.output<typeof zJobView>;
export type JobPage = z.output<typeof zJobPage>;
export type JobStatus = z.output<typeof zJobStatus>;
export type Estimate = z.output<typeof zEstimateView>;
export type Storyboard = z.output<typeof zStoryboard>;
export type StoryboardScene = z.output<typeof zStoryboardScene>;
export type StoryboardView = z.output<typeof zStoryboardView>;
export type StoryboardIssue = z.output<typeof zStoryboardIssue>;
export type StoryboardLimits = z.output<typeof zStoryboardLimitsView>;
export type StyleOption = z.output<typeof zStyleView>;
export type ShareLink = z.output<typeof zShareLinkView>;

export type ConnectionState = "connecting" | "live" | "reconnecting" | "polling";

export interface EstimateInput {
  durationSeconds: number;
  aspects: readonly Aspect[];
  voiceId: string | null;
}

export interface JobFilters {
  status?: JobStatus;
}

export type TimelineStatus = "pending" | "active" | "done" | "skipped" | "failed" | "cancelled";

export interface TimelineRow {
  key: string;
  label: string;
  status: TimelineStatus;
  detail: string | null;
  durationMs: number | null;
}

export interface TimelineModel {
  rows: readonly TimelineRow[];
  renderProgress: number;
  announcement: string;
}
