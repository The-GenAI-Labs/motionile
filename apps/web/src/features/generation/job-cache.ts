import { isTerminalEvent, type JobEvent } from "@/features/generation/schemas/generation.schema";
import type { Job, JobStatus } from "@/features/generation/types/generation.types";

const STATUS_BY_STAGE: Readonly<Record<string, JobStatus>> = {
  guard: "planning",
  context: "planning",
  plan: "planning",
  critique: "planning",
  approval: "awaiting_approval",
  voice: "voicing",
  scenes: "generating",
  compose: "generating",
  repair: "generating",
  validate: "validating",
  visual_review: "validating",
  render: "rendering",
  finalize: "rendering",
};

const TERMINAL: readonly JobStatus[] = ["completed", "failed", "cancelled"];

export const payloadString = (payload: JobEvent["payload"], key: string): string | null => {
  const value = payload[key];
  return typeof value === "string" ? value : null;
};

export const payloadNumber = (payload: JobEvent["payload"], key: string): number | null => {
  const value = payload[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
};

export const payloadBoolean = (payload: JobEvent["payload"], key: string): boolean | null => {
  const value = payload[key];
  return typeof value === "boolean" ? value : null;
};

export const payloadStrings = (payload: JobEvent["payload"], key: string): string[] => {
  const value = payload[key];
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
};

export const statusForStage = (stage: string): JobStatus | null => STATUS_BY_STAGE[stage] ?? null;

const isTerminal = (status: JobStatus): boolean => TERMINAL.includes(status);

export const applyEventToJob = (job: Job, event: JobEvent): Job => {
  if (isTerminal(job.status)) {
    return job;
  }
  const { payload } = event;
  switch (event.type) {
    case "stage.started": {
      const stage = payloadString(payload, "stage") ?? event.stage;
      if (stage === null) {
        return job;
      }
      return { ...job, currentStage: stage, status: statusForStage(stage) ?? job.status };
    }
    case "approval.requested":
      return { ...job, status: "awaiting_approval", currentStage: "approval" };
    case "approval.granted":
      return { ...job, status: "voicing", currentStage: "voice" };
    case "job.cancel_requested":
      return { ...job, cancelRequestedAt: event.at };
    case "job.completed":
      return {
        ...job,
        status: "completed",
        completedAt: event.at,
        creditsCharged: payloadNumber(payload, "creditsCharged") ?? job.creditsCharged,
        fallbackSceneIds: payloadStrings(payload, "fallbackSceneIds"),
      };
    case "job.failed":
      return {
        ...job,
        status: "failed",
        completedAt: event.at,
        errorCode: payloadString(payload, "code") ?? job.errorCode,
        errorMessage: payloadString(payload, "message") ?? job.errorMessage,
      };
    case "job.cancelled":
      return {
        ...job,
        status: "cancelled",
        completedAt: event.at,
        errorCode: payloadString(payload, "code") ?? job.errorCode,
        errorMessage: payloadString(payload, "message") ?? job.errorMessage,
      };
    default:
      return job;
  }
};

export const newerJob = (current: Job | undefined, incoming: Job): Job => {
  if (current === undefined) {
    return incoming;
  }
  return Date.parse(incoming.updatedAt) >= Date.parse(current.updatedAt) ? incoming : current;
};

export const mergeEvent = (events: readonly JobEvent[], event: JobEvent): readonly JobEvent[] => {
  if (event.id === null) {
    const index = events.findIndex((item) => item.id === null && item.type === event.type);
    return index === -1
      ? [...events, event]
      : events.map((item, i) => (i === index ? event : item));
  }
  return events.some((item) => item.id === event.id) ? events : [...events, event];
};

export const lastStoredEventId = (events: readonly JobEvent[] | undefined): string | null => {
  const stored = events?.findLast((event) => event.id !== null);
  return stored?.id ?? null;
};

export const hasTerminalEvent = (events: readonly JobEvent[] | undefined): boolean =>
  events?.some(isTerminalEvent) ?? false;

export const REFRESH_EVENT_TYPES: ReadonlySet<string> = new Set([
  "approval.requested",
  "approval.granted",
  "job.cancel_requested",
  "job.completed",
  "job.failed",
  "job.cancelled",
]);

export const STORYBOARD_EVENT_TYPES: ReadonlySet<string> = new Set([
  "storyboard.ready",
  "storyboard.updated",
  "approval.requested",
]);
