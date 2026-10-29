import type {
  zDiffView,
  zEvalRunView,
  zEvalStatus,
  zRunStatus,
  zTemplateView,
  zVersionView,
} from "@motionile/api-contract";
import type { z } from "zod";

export type PromptTemplate = z.output<typeof zTemplateView>;
export type PromptVersion = z.output<typeof zVersionView>;
export type PromptDiff = z.output<typeof zDiffView>;
export type EvalRun = z.output<typeof zEvalRunView>;
export type EvalStatus = z.output<typeof zEvalStatus>;
export type RunStatus = z.output<typeof zRunStatus>;

export interface EvalRunFilters {
  suite?: string;
  status?: RunStatus;
}

export interface DiffRequest {
  key: string;
  from: number;
  to: number;
}

export interface StartEvalRunInput {
  suite: string;
  versionIds: string[];
}

export interface DraftInput {
  body: string;
  variables: string[];
}

export type DiffLineKind = "header" | "hunk" | "added" | "removed" | "context";

export interface DiffLine {
  id: number;
  kind: DiffLineKind;
  text: string;
}

export interface ActivationBlock {
  missingSuites: string[];
  failedSuites: string[];
}
