import type {
  zAdminEventView,
  zAdminJobDetail,
  zAdminJobSummary,
  zAdminSceneView,
  zJobAnalyticsView,
  zJobSource,
  zJobStatus,
} from "@motionile/api-contract";
import type { z } from "zod";

export type AdminJobSummary = z.output<typeof zAdminJobSummary>;
export type AdminJobDetail = z.output<typeof zAdminJobDetail>;
export type AdminJobEvent = z.output<typeof zAdminEventView>;
export type AdminJobScene = z.output<typeof zAdminSceneView>;
export type JobAnalytics = z.output<typeof zJobAnalyticsView>;
export type JobStatus = z.output<typeof zJobStatus>;
export type JobSource = z.output<typeof zJobSource>;

export interface AdminJobFilters {
  status?: JobStatus;
  source?: JobSource;
  userId?: string;
  createdFrom?: string;
  createdTo?: string;
}

export interface AnalyticsRange {
  from: string;
  to: string;
}

export interface IssueCount {
  code: string;
  count: number;
}

export interface ReportSummary {
  valid: boolean | null;
  errors: number | null;
  warnings: number | null;
  issueCounts: IssueCount[];
  skipped: number;
}
