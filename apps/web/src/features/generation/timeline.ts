import {
  payloadBoolean,
  payloadNumber,
  payloadString,
  payloadStrings,
} from "@/features/generation/job-cache";
import type { JobEvent } from "@/features/generation/schemas/generation.schema";
import type {
  Job,
  TimelineModel,
  TimelineRow,
  TimelineStatus,
} from "@/features/generation/types/generation.types";

interface StageDefinition {
  key: string;
  label: string;
  nodes: readonly string[];
  optional: boolean;
}

export const stageDefinitions = [
  { key: "guard", label: "Safety check", nodes: ["guard"], optional: false },
  { key: "context", label: "Gathering context", nodes: ["context"], optional: false },
  { key: "plan", label: "Planning the storyboard", nodes: ["plan"], optional: false },
  { key: "critique", label: "Reviewing the plan", nodes: ["critique"], optional: false },
  { key: "approval", label: "Your review", nodes: ["approval"], optional: true },
  { key: "voice", label: "Recording narration", nodes: ["voice"], optional: false },
  { key: "scenes", label: "Building scenes", nodes: ["scenes", "compose"], optional: false },
  { key: "validate", label: "Checking layout", nodes: ["validate"], optional: false },
  { key: "review", label: "Visual review", nodes: ["visual_review"], optional: true },
  { key: "repair", label: "Repairing scenes", nodes: ["repair"], optional: true },
  { key: "render", label: "Rendering video", nodes: ["render", "finalize"], optional: false },
] as const satisfies readonly StageDefinition[];

export const statusLabels = {
  pending: "Waiting",
  active: "In progress",
  done: "Done",
  skipped: "Skipped",
  failed: "Failed",
  cancelled: "Stopped",
} as const satisfies Record<TimelineStatus, string>;

interface RowState {
  started: boolean;
  completed: boolean;
  durationMs: number;
}

interface Tally {
  sceneCount: number | null;
  voiced: Set<string>;
  generated: Set<string>;
  repaired: Set<string>;
  fallback: Set<string>;
  skills: number | null;
  revised: boolean | null;
  blockingIssues: number | null;
  validationErrors: number | null;
  validationWarnings: number | null;
  reviewIssues: number | null;
  renderProgress: number;
  approvalRequested: boolean;
}

const stageIndexOf = (node: string): number =>
  stageDefinitions.findIndex((definition) =>
    (definition.nodes as readonly string[]).includes(node),
  );

const plural = (count: number, singular: string, pluralForm = `${singular}s`): string =>
  `${String(count)} ${count === 1 ? singular : pluralForm}`;

const emptyTally = (): Tally => ({
  sceneCount: null,
  voiced: new Set(),
  generated: new Set(),
  repaired: new Set(),
  fallback: new Set(),
  skills: null,
  revised: null,
  blockingIssues: null,
  validationErrors: null,
  validationWarnings: null,
  reviewIssues: null,
  renderProgress: 0,
  approvalRequested: false,
});

const addScene = (target: Set<string>, event: JobEvent): void => {
  const sceneId = payloadString(event.payload, "sceneId");
  if (sceneId !== null) {
    target.add(sceneId);
  }
};

const tallyEvent = (tally: Tally, event: JobEvent): void => {
  const { payload } = event;
  switch (event.type) {
    case "context.ready":
      tally.skills = payloadStrings(payload, "skills").length;
      break;
    case "storyboard.ready":
      tally.sceneCount = payloadNumber(payload, "sceneCount") ?? tally.sceneCount;
      break;
    case "critique.completed":
      tally.revised = payloadBoolean(payload, "revised");
      tally.blockingIssues = payloadNumber(payload, "blockingIssues");
      break;
    case "approval.requested":
      tally.approvalRequested = true;
      break;
    case "scene.voiced":
      addScene(tally.voiced, event);
      break;
    case "scene.generated":
      addScene(tally.generated, event);
      break;
    case "scene.repaired":
      addScene(tally.repaired, event);
      break;
    case "scene.fallback":
      addScene(tally.fallback, event);
      break;
    case "validation.completed":
      tally.validationErrors = payloadNumber(payload, "errors");
      tally.validationWarnings = payloadNumber(payload, "warnings");
      break;
    case "review.completed":
      tally.reviewIssues = payloadNumber(payload, "issues");
      break;
    case "render.progress":
      tally.renderProgress = Math.max(
        tally.renderProgress,
        Math.round(payloadNumber(payload, "progress") ?? 0),
      );
      break;
    default:
      break;
  }
};

const ofTotal = (done: number, total: number | null, verb: string): string =>
  total === null
    ? `${plural(done, "scene")} ${verb}`
    : `${String(done)} of ${String(total)} scenes ${verb}`;

const detailFor = (key: string, status: TimelineStatus, tally: Tally): string | null => {
  switch (key) {
    case "context":
      return tally.skills === null ? null : `${plural(tally.skills, "skill")} selected`;
    case "plan":
      return tally.sceneCount === null ? null : `${plural(tally.sceneCount, "scene")} planned`;
    case "critique":
      if (tally.blockingIssues !== null && tally.blockingIssues > 0) {
        return `${plural(tally.blockingIssues, "blocking issue")} found`;
      }
      return tally.revised === null ? null : tally.revised ? "Plan revised" : "No changes needed";
    case "approval":
      if (status === "active") {
        return "Waiting for you to review the storyboard";
      }
      return status === "skipped" ? "Review is off for this video" : null;
    case "voice":
      return tally.voiced.size === 0 && status === "pending"
        ? null
        : ofTotal(tally.voiced.size, tally.sceneCount, "voiced");
    case "scenes":
      return tally.generated.size === 0 && status === "pending"
        ? null
        : ofTotal(tally.generated.size, tally.sceneCount, "generated");
    case "validate":
      return tally.validationErrors === null
        ? null
        : `${plural(tally.validationErrors, "error")}, ${plural(tally.validationWarnings ?? 0, "warning")}`;
    case "review":
      return tally.reviewIssues === null ? null : `${plural(tally.reviewIssues, "issue")} found`;
    case "repair":
      if (status === "skipped") {
        return "Not needed";
      }
      return tally.repaired.size === 0 && tally.fallback.size === 0
        ? null
        : `${String(tally.repaired.size)} repaired, ${String(tally.fallback.size)} with a simple layout`;
    case "render":
      return status === "pending" ? null : `${String(tally.renderProgress)}% rendered`;
    default:
      return null;
  }
};

const newRowStates = (): RowState[] =>
  stageDefinitions.map(() => ({ started: false, completed: false, durationMs: 0 }));

interface Walk {
  rows: RowState[];
  tally: Tally;
  activeIndex: number | null;
  furthest: number;
}

const startStage = (walk: Walk, index: number): void => {
  if (index < 0) {
    return;
  }
  if (walk.activeIndex !== null && walk.activeIndex !== index) {
    const previous = walk.rows[walk.activeIndex];
    if (previous) {
      previous.completed = true;
    }
  }
  const row = walk.rows[index];
  if (row) {
    row.started = true;
  }
  walk.activeIndex = index;
  walk.furthest = Math.max(walk.furthest, index);
};

const completeStage = (walk: Walk, index: number, durationMs: number | null): void => {
  const row = walk.rows[index];
  if (!row) {
    return;
  }
  row.started = true;
  row.completed = true;
  row.durationMs += durationMs ?? 0;
  if (walk.activeIndex === index) {
    walk.activeIndex = null;
  }
};

const walkEvents = (events: readonly JobEvent[]): Walk => {
  const walk: Walk = { rows: newRowStates(), tally: emptyTally(), activeIndex: null, furthest: -1 };
  for (const event of events) {
    tallyEvent(walk.tally, event);
    const node = payloadString(event.payload, "stage") ?? event.stage;
    if (event.type === "stage.started" && node !== null) {
      startStage(walk, stageIndexOf(node));
    } else if (event.type === "stage.completed" && node !== null) {
      completeStage(walk, stageIndexOf(node), payloadNumber(event.payload, "durationMs"));
    } else if (event.type === "approval.requested") {
      startStage(walk, stageIndexOf("approval"));
    } else if (event.type === "approval.granted") {
      completeStage(walk, stageIndexOf("approval"), null);
    }
  }
  return walk;
};

const baselineFromJob = (job: Job, walk: Walk): void => {
  const current = job.currentStage === null ? -1 : stageIndexOf(job.currentStage);
  if (job.status === "awaiting_approval") {
    startStage(walk, stageIndexOf("approval"));
    return;
  }
  if (current >= 0) {
    for (let index = 0; index < current; index += 1) {
      const row = walk.rows[index];
      if (row) {
        row.started = true;
        row.completed = true;
      }
    }
    startStage(walk, current);
  }
};

const resolveStatus = (
  index: number,
  state: RowState,
  walk: Walk,
  job: Job,
  optional: boolean,
): TimelineStatus => {
  if (job.status === "completed") {
    return state.started || !optional ? "done" : "skipped";
  }
  const stopped = job.status === "failed" || job.status === "cancelled";
  if (walk.activeIndex === index) {
    if (!stopped) {
      return "active";
    }
    return job.status === "cancelled" ? "cancelled" : "failed";
  }
  if (state.started) {
    return stopped && !state.completed
      ? job.status === "cancelled"
        ? "cancelled"
        : "failed"
      : "done";
  }
  if (walk.furthest > index) {
    return optional ? "skipped" : "done";
  }
  return "pending";
};

const announce = (job: Job, rows: readonly TimelineRow[]): string => {
  if (job.status === "completed") {
    return "Your video is ready.";
  }
  if (job.status === "failed") {
    return "The video could not be made.";
  }
  if (job.status === "cancelled") {
    return "The video was cancelled.";
  }
  if (job.status === "queued") {
    return "Your video is queued.";
  }
  const active = rows.find((row) => row.status === "active");
  if (!active) {
    return "Working on your video.";
  }
  return active.detail === null ? `${active.label}.` : `${active.label}. ${active.detail}.`;
};

export const buildTimeline = (job: Job, events: readonly JobEvent[]): TimelineModel => {
  const walk = walkEvents(events);
  if (events.length === 0 || (walk.furthest === -1 && !walk.tally.approvalRequested)) {
    baselineFromJob(job, walk);
  }
  const rows = stageDefinitions.map((definition, index): TimelineRow => {
    const state = walk.rows[index] ?? { started: false, completed: false, durationMs: 0 };
    const status = resolveStatus(index, state, walk, job, definition.optional);
    const approvalOff = definition.key === "approval" && !job.options.reviewStoryboard;
    const finalStatus = approvalOff && !state.started ? "skipped" : status;
    return {
      key: definition.key,
      label: definition.label,
      status: finalStatus,
      detail: detailFor(definition.key, finalStatus, walk.tally),
      durationMs: state.durationMs > 0 ? state.durationMs : null,
    };
  });
  const renderProgress = job.status === "completed" ? 100 : walk.tally.renderProgress;
  return { rows, renderProgress, announcement: announce(job, rows) };
};
