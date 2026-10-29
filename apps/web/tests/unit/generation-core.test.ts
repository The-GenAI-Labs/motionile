import { describe, expect, it } from "vitest";

import {
  explainFailure,
  generationErrorMessage,
  isPolicyRefusal,
  isRetryableSubmitError,
} from "@/features/generation/errors";
import {
  applyEventToJob,
  hasTerminalEvent,
  lastStoredEventId,
  mergeEvent,
  newerJob,
} from "@/features/generation/job-cache";
import {
  buildCreateRequest,
  createJobFormSchema,
  decodeEstimateSignature,
  estimateSignature,
  parseJobEvent,
} from "@/features/generation/schemas/generation.schema";
import {
  newSceneDraft,
  nextSceneId,
  onScreenCharacterLimit,
  rateVerdict,
  sceneIndexFromField,
  spokenSeconds,
  toDraft,
  toStoryboard,
  totalVerdict,
} from "@/features/generation/schemas/storyboard.schema";
import { buildTimeline } from "@/features/generation/timeline";
import { ApiError } from "@/lib/api/api-error";

import { event, job, storyboardView, TOPIC_ID } from "./generation-fixtures";

const problem = (status: number, code: string, extensions: Record<string, string | number> = {}) =>
  new ApiError({ kind: "http", status, code, title: "Problem", detail: "Detail", extensions });

const validForm = {
  topicId: null,
  topicTitle: null,
  query: "How does DNS work?",
  durationSeconds: 60,
  aspects: ["16:9"] as const,
  style: "minimal-dark",
  voiceId: null,
  language: "en",
  reviewStoryboard: false,
  subtitles: true,
  burnInSubtitles: false,
};

describe("generation error mapping", () => {
  it("maps the known problem codes to clear messages", () => {
    expect(generationErrorMessage(problem(409, "too_many_active_jobs", { limit: 2 }))).toContain(
      "2 videos in progress",
    );
    expect(generationErrorMessage(problem(404, "topic_not_found"))).toContain(
      "no longer available",
    );
    expect(generationErrorMessage(problem(422, "style_not_found"))).toContain("style");
    expect(generationErrorMessage(problem(402, "insufficient_credits", { shortfall: 30 }))).toBe(
      "You need 30 more credits for this video.",
    );
    expect(generationErrorMessage(problem(402, "insufficient_credits"))).toContain(
      "do not have enough credits",
    );
  });

  it("shows the policy message of a refused input", () => {
    const refusal = problem(422, "input_refused", { policy: "policy_weapons" });
    expect(generationErrorMessage(refusal)).toBe("Detail");
  });

  it("explains rate limits through the shared auth messages", () => {
    const limited = new ApiError({
      kind: "http",
      status: 429,
      code: "rate_limited",
      title: "Slow down",
      detail: null,
      retryAfterSeconds: 12,
    });
    expect(generationErrorMessage(limited)).toContain("12 seconds");
  });

  it("separates policy refusals from other failures", () => {
    expect(isPolicyRefusal("policy_malware")).toBe(true);
    expect(isPolicyRefusal("policy_output_blocked")).toBe(false);
    expect(isPolicyRefusal(null)).toBe(false);
  });

  it("explains failed and cancelled jobs", () => {
    expect(
      explainFailure("failed", "policy_abuse", "Request not supported", "Not allowed."),
    ).toEqual({
      title: "Request not supported",
      message: "Not allowed.",
      refusal: true,
    });
    expect(explainFailure("failed", "tts_failed", null, null).message).toContain(
      "credits were returned",
    );
    expect(explainFailure("cancelled", "approval_expired", null, null).title).toBe(
      "Video cancelled",
    );
  });

  it("retries only transient submit failures", () => {
    expect(isRetryableSubmitError(ApiError.ofKind("network"))).toBe(true);
    expect(isRetryableSubmitError(problem(409, "idempotency_request_in_progress"))).toBe(true);
    expect(isRetryableSubmitError(problem(422, "style_not_found"))).toBe(false);
  });
});

describe("create form schema", () => {
  it("accepts a query job and builds the request", () => {
    const parsed = createJobFormSchema.parse(validForm);
    const request = buildCreateRequest(parsed);
    expect(request.query).toBe("How does DNS work?");
    expect(request.topicId).toBeNull();
    expect(request.options.durationSeconds).toBe(60);
  });

  it("sends only the topic for a catalog job", () => {
    const parsed = createJobFormSchema.parse({ ...validForm, topicId: TOPIC_ID, query: "ignored" });
    const request = buildCreateRequest(parsed);
    expect(request.topicId).toBe(TOPIC_ID);
    expect(request.query).toBeNull();
  });

  it("requires a topic or a question, an aspect and subtitles for burn-in", () => {
    const empty = createJobFormSchema.safeParse({ ...validForm, query: "  " });
    expect(empty.error?.issues[0]?.path).toEqual(["query"]);
    const noAspect = createJobFormSchema.safeParse({ ...validForm, aspects: [] });
    expect(noAspect.error?.issues[0]?.message).toBe("Choose at least one aspect ratio.");
    const burn = createJobFormSchema.safeParse({
      ...validForm,
      subtitles: false,
      burnInSubtitles: true,
    });
    expect(burn.error?.issues[0]?.path).toEqual(["burnInSubtitles"]);
    const short = createJobFormSchema.safeParse({ ...validForm, durationSeconds: 5 });
    expect(short.success).toBe(false);
  });

  it("round trips the estimate signature regardless of aspect order", () => {
    const signature = estimateSignature({
      durationSeconds: 45,
      aspects: ["9:16", "16:9"],
      voiceId: null,
    });
    expect(signature).toBe("45|16:9,9:16|");
    expect(decodeEstimateSignature(signature)).toEqual({
      durationSeconds: 45,
      aspects: ["16:9", "9:16"],
      voiceId: null,
    });
  });
});

describe("job cache helpers", () => {
  it("parses stream messages and rejects malformed ones", () => {
    expect(parseJobEvent("not json")).toBeNull();
    expect(parseJobEvent(JSON.stringify({ type: 1 }))).toBeNull();
    const ok = event("stage.started", { stage: "plan" }, 1, "plan");
    expect(parseJobEvent(JSON.stringify(ok))).toEqual(ok);
  });

  it("deduplicates stored events and keeps one progress frame", () => {
    const first = event("scene.voiced", { sceneId: "s1" }, 1);
    const merged = mergeEvent(mergeEvent([], first), first);
    expect(merged).toHaveLength(1);
    const progress = { ...event("render.progress", { progress: 10 }), id: null };
    const next = mergeEvent(mergeEvent(merged, progress), {
      ...progress,
      payload: { progress: 20 },
    });
    expect(next).toHaveLength(2);
    expect(next[1]?.payload["progress"]).toBe(20);
    expect(lastStoredEventId(next)).toBe(first.id);
    expect(lastStoredEventId(undefined)).toBeNull();
  });

  it("patches the job from events and never leaves a terminal state", () => {
    const started = applyEventToJob(job(), event("stage.started", { stage: "voice" }));
    expect(started.status).toBe("voicing");
    expect(applyEventToJob(job(), event("approval.requested", {})).status).toBe(
      "awaiting_approval",
    );
    const done = applyEventToJob(
      job(),
      event("job.completed", { creditsCharged: 120, fallbackSceneIds: ["s2"] }),
    );
    expect(done).toMatchObject({
      status: "completed",
      creditsCharged: 120,
      fallbackSceneIds: ["s2"],
    });
    expect(applyEventToJob(done, event("stage.started", { stage: "plan" })).status).toBe(
      "completed",
    );
    const failed = applyEventToJob(
      job(),
      event("job.failed", { code: "tts_failed", message: "No voice" }),
    );
    expect(failed).toMatchObject({
      status: "failed",
      errorCode: "tts_failed",
      errorMessage: "No voice",
    });
  });

  it("keeps the newer job and detects terminal events", () => {
    const older = job({ updatedAt: "2026-10-25T10:00:00Z" });
    const newer = job({ updatedAt: "2026-10-25T10:05:00Z", status: "voicing" });
    expect(newerJob(newer, older)).toBe(newer);
    expect(newerJob(undefined, older)).toBe(older);
    expect(hasTerminalEvent([event("job.cancelled")])).toBe(true);
    expect(hasTerminalEvent([event("stage.started")])).toBe(false);
  });
});

describe("timeline", () => {
  it("falls back to the job stage when there are no events", () => {
    const timeline = buildTimeline(
      job({ currentStage: "plan", options: { ...job().options, reviewStoryboard: true } }),
      [],
    );
    const byKey = Object.fromEntries(timeline.rows.map((row) => [row.key, row.status]));
    expect(byKey["guard"]).toBe("done");
    expect(byKey["plan"]).toBe("active");
    expect(byKey["voice"]).toBe("pending");
  });

  it("reports scene counts, repairs and fallbacks", () => {
    const events = [
      event("stage.started", { stage: "plan" }, 1),
      event("storyboard.ready", { version: 1, sceneCount: 3 }, 2),
      event("stage.completed", { stage: "plan", durationMs: 4000 }, 3),
      event("approval.requested", {}, 4),
      event("approval.granted", {}, 5),
      event("stage.started", { stage: "voice" }, 6),
      event("scene.voiced", { sceneId: "s1" }, 7),
      event("scene.voiced", { sceneId: "s2" }, 8),
      event("stage.started", { stage: "scenes" }, 9),
      event("scene.generated", { sceneId: "s1" }, 10),
      event("stage.started", { stage: "validate" }, 11),
      event("validation.completed", { errors: 1, warnings: 2 }, 12),
      event("stage.started", { stage: "repair" }, 13),
      event("scene.repaired", { sceneId: "s1", attempt: 1 }, 14),
      event("scene.fallback", { sceneId: "s2", reason: "invalid" }, 15),
      event("stage.started", { stage: "render" }, 16),
      event("render.progress", { progress: 40 }, 17),
    ];
    const timeline = buildTimeline(job({ status: "rendering", currentStage: "render" }), events);
    const rows = Object.fromEntries(timeline.rows.map((row) => [row.key, row]));
    expect(rows["plan"]).toMatchObject({
      status: "done",
      detail: "3 scenes planned",
      durationMs: 4000,
    });
    expect(rows["voice"]).toMatchObject({ status: "done", detail: "2 of 3 scenes voiced" });
    expect(rows["scenes"]?.detail).toBe("1 of 3 scenes generated");
    expect(rows["validate"]?.detail).toBe("1 error, 2 warnings");
    expect(rows["repair"]?.detail).toBe("1 repaired, 1 with a simple layout");
    expect(rows["render"]).toMatchObject({ status: "active", detail: "40% rendered" });
    expect(timeline.renderProgress).toBe(40);
    expect(timeline.announcement).toBe("Rendering video. 40% rendered.");
    expect(rows["review"]?.status).toBe("skipped");
  });

  it("marks the running stage failed and skips the review that was off", () => {
    const events = [
      event("stage.started", { stage: "guard" }, 1),
      event("stage.completed", { stage: "guard", durationMs: 10 }, 2),
      event("stage.started", { stage: "plan" }, 3),
    ];
    const failed = job({
      status: "failed",
      options: { ...job().options, reviewStoryboard: false },
    });
    const rows = Object.fromEntries(
      buildTimeline(failed, events).rows.map((row) => [row.key, row]),
    );
    expect(rows["plan"]?.status).toBe("failed");
    expect(rows["approval"]?.status).toBe("skipped");
    expect(rows["voice"]?.status).toBe("pending");
  });

  it("shows every stage done for a completed job", () => {
    const rows = buildTimeline(job({ status: "completed" }), []).rows;
    expect(rows.find((row) => row.key === "plan")?.status).toBe("done");
    expect(rows.find((row) => row.key === "repair")?.status).toBe("skipped");
  });
});

describe("storyboard helpers", () => {
  it("creates unique scene ids", () => {
    expect(nextSceneId(["s1", "s2", "intro"])).toBe("s3");
    expect(nextSceneId([])).toBe("s1");
    expect(newSceneDraft(["s7"]).sceneId).toBe("s8");
  });

  it("rewrites positions from the order and keeps untouched fields", () => {
    const view = storyboardView();
    const draft = toDraft(view.content);
    const reordered = {
      ...draft,
      scenes: [draft.scenes[2], draft.scenes[0], draft.scenes[1]] as typeof draft.scenes,
    };
    const saved = toStoryboard(view.content, reordered);
    expect(saved.scenes.map((item) => [item.id, item.position])).toEqual([
      ["s3", 0],
      ["s1", 1],
      ["s2", 2],
    ]);
    expect(saved.scenes[0]?.layoutNotes).toEqual({ "16:9": "Centered" });
    expect(saved.scenes[0]?.targetDurationMs).toBe(4000);
  });

  it("gives a new scene layout notes for every aspect", () => {
    const view = storyboardView();
    const draft = toDraft(view.content);
    const added = {
      ...draft,
      scenes: [
        ...draft.scenes,
        {
          ...newSceneDraft(["s1", "s2", "s3"]),
          goal: "Goal",
          narration: "Words",
          visualBrief: "Brief",
        },
      ],
    };
    const saved = toStoryboard(view.content, added);
    expect(saved.scenes[3]?.layoutNotes["16:9"]).toBeTruthy();
    expect(saved.scenes[3]?.position).toBe(3);
  });

  it("estimates speech and judges the speaking rate and totals", () => {
    const { limits } = storyboardView();
    const narration = "word ".repeat(12).trim();
    expect(spokenSeconds(narration, limits)).toBeCloseTo(5);
    expect(rateVerdict(narration, 2, limits)).toBe("too_fast");
    expect(rateVerdict(narration, 20, limits)).toBe("too_slow");
    expect(rateVerdict(narration, 5, limits)).toBe("ok");
    expect(totalVerdict(12, 12, 10)).toBe("ok");
    expect(totalVerdict(14, 12, 10)).toBe("too_long");
    expect(totalVerdict(9, 12, 10)).toBe("too_short");
    expect(onScreenCharacterLimit(limits, ["16:9"])).toBe(160);
  });

  it("maps field paths to scene positions", () => {
    expect(sceneIndexFromField("content.scenes.2")).toBe(2);
    expect(sceneIndexFromField("body.content.scenes.1.narration")).toBe(1);
    expect(sceneIndexFromField("content")).toBeNull();
  });
});
