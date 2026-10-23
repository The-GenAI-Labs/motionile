import { describe, expect, it } from "vitest";

import {
  adminRenderErrorMessage,
  renderFailureGuidance,
  renderFailureMessage,
} from "@/features/admin-render/errors";
import {
  audioPartName,
  buildGoldenRequest,
  buildRenderOptions,
  buildTestbedForm,
} from "@/features/admin-render/multipart";
import {
  initialProgressState,
  MAX_STREAM_ATTEMPTS,
  progressReducer,
  reconnectDelayMs,
} from "@/features/admin-render/progress-reducer";
import { extractSceneIds, extractScenes } from "@/features/admin-render/scene-ids";
import {
  audioFileError,
  compositionFileError,
  emptyGoldenFormValues,
  emptyRenderFormValues,
  goldenFormSchema,
  parseStageTimings,
  parseValidationReport,
  renderFormSchema,
  type RenderFormValues,
  sortIssues,
} from "@/features/admin-render/schemas/admin-render.schema";
import { createSseParser, type SseFrame } from "@/features/admin-render/sse";
import { ApiError } from "@/lib/api/api-error";
import { formatTimestampMs } from "@/lib/utils/format";

const VOICE_ID = "0197c5a2-1b2c-7d3e-8f40-5a6b7c8d9f01";
const MUSIC_ID = "0197c5a2-1b2c-7d3e-8f40-5a6b7c8d9f02";
const RENDER_ID = "0197c5a2-1b2c-7d3e-8f40-5a6b7c8d9f03";

const html = (name = "composition.html", size?: number) => {
  const file = new File(["<html></html>"], name, { type: "text/html" });
  if (size !== undefined) {
    Object.defineProperty(file, "size", { value: size });
  }
  return file;
};

const synthesizeValues = (overrides: Partial<RenderFormValues> = {}): RenderFormValues => ({
  ...emptyRenderFormValues(),
  composition: html(),
  voiceId: VOICE_ID,
  scenes: [
    { sceneId: "intro", text: "  Hello there.  " },
    { sceneId: "outro", text: "Goodbye." },
  ],
  ...overrides,
});

describe("scene id extraction", () => {
  it("reads data-scene values in document order", () => {
    const ids = extractSceneIds(
      '<body><section data-scene="intro"></section><div><p data-scene="middle"></p></div><section data-scene="outro"></section></body>',
    );

    expect(ids).toEqual(["intro", "middle", "outro"]);
  });

  it("reports empty, invalid and duplicate scene ids without listing them twice", () => {
    const { sceneIds, issues } = extractScenes(
      '<section data-scene="a"></section><section data-scene=""></section><section data-scene="bad id!"></section><section data-scene="a"></section>',
    );

    expect(sceneIds).toEqual(["a"]);
    expect(issues).toHaveLength(3);
    expect(issues.join(" ")).toContain("bad id!");
    expect(issues.join(" ")).toContain("more than once");
  });

  it("returns nothing for a document without scenes", () => {
    expect(extractScenes("<p>No scenes</p>")).toEqual({ sceneIds: [], issues: [] });
  });
});

describe("render options and multipart builder", () => {
  it("builds synthesize options with trimmed text, the voice and no music", () => {
    expect(buildRenderOptions(synthesizeValues())).toEqual({
      aspects: ["16:9", "9:16", "1:1"],
      fps: 30,
      musicTrackId: null,
      subtitles: true,
      burnInSubtitles: false,
      narration: {
        mode: "synthesize",
        voiceId: VOICE_ID,
        scenes: [
          { sceneId: "intro", text: "Hello there." },
          { sceneId: "outro", text: "Goodbye." },
        ],
      },
    });
  });

  it("never sends burn-in without subtitles", () => {
    const options = buildRenderOptions(
      synthesizeValues({ subtitles: false, burnInSubtitles: true, musicTrackId: MUSIC_ID }),
    );

    expect(options.subtitles).toBe(false);
    expect(options.burnInSubtitles).toBe(false);
    expect(options.musicTrackId).toBe(MUSIC_ID);
  });

  it("sends the composition, the options JSON and nothing else for synthesized narration", () => {
    const form = buildTestbedForm(synthesizeValues());

    expect([...form.keys()].toSorted()).toEqual(["composition", "options"]);
    expect((form.get("composition") as File).name).toBe("composition.html");
    expect(typeof form.get("options")).toBe("string");
    expect(JSON.parse(form.get("options") as string)).toMatchObject({
      narration: { mode: "synthesize", voiceId: VOICE_ID },
    });
  });

  it("names every uploaded audio part by the audioPart in the options", () => {
    const first = new File(["a"], "intro.mp3", { type: "audio/mpeg" });
    const second = new File(["b"], "outro.wav", { type: "audio/wav" });
    const form = buildTestbedForm(
      synthesizeValues({
        mode: "upload",
        voiceId: "",
        scenes: [
          { sceneId: "intro", text: "", audio: first },
          { sceneId: "outro", text: "Optional words", audio: second },
        ],
      }),
    );
    const options = JSON.parse(form.get("options") as string) as {
      narration: { scenes: { sceneId: string; audioPart: string; text?: string }[] };
    };

    expect(options.narration.scenes).toEqual([
      { sceneId: "intro", audioPart: audioPartName(0) },
      { sceneId: "outro", audioPart: audioPartName(1), text: "Optional words" },
    ]);
    expect(form.get(audioPartName(0))).toBeInstanceOf(File);
    expect((form.get(audioPartName(1)) as File).name).toBe("outro.wav");
    expect([...form.keys()].toSorted()).toEqual(
      ["audio-0", "audio-1", "composition", "options"].toSorted(),
    );
  });

  it("refuses to build a form without a composition or a scene audio file", () => {
    expect(() => buildTestbedForm(synthesizeValues({ composition: undefined }))).toThrow(
      "composition",
    );
    expect(() =>
      buildTestbedForm(
        synthesizeValues({
          mode: "upload",
          voiceId: "",
          scenes: [{ sceneId: "intro", text: "" }],
        }),
      ),
    ).toThrow("intro");
  });

  it("builds the golden request with the chosen voice and concrete fps", () => {
    expect(
      buildGoldenRequest({
        ...emptyGoldenFormValues(),
        voiceId: VOICE_ID,
        aspects: ["9:16"],
        fps: "24",
        musicTrackId: MUSIC_ID,
      }),
    ).toEqual({
      voiceId: VOICE_ID,
      aspects: ["9:16"],
      fps: 24,
      musicTrackId: MUSIC_ID,
      subtitles: true,
      burnInSubtitles: false,
    });
  });
});

describe("render form validation", () => {
  const issuesFor = (values: RenderFormValues) => {
    const result = renderFormSchema.safeParse(values);
    return result.success
      ? []
      : result.error.issues.map((issue) => `${issue.path.join(".")}: ${issue.message}`);
  };

  it("accepts a valid synthesize form", () => {
    expect(issuesFor(synthesizeValues())).toEqual([]);
  });

  it("checks the composition file type and size", () => {
    expect(compositionFileError(html("page.txt"))).toBe("The composition must be an .html file.");
    expect(compositionFileError(html("big.html", 4 * 1024 * 1024 + 1))).toBe(
      "The file is larger than 4 MB.",
    );
    expect(compositionFileError(html("ok.HTML", 4 * 1024 * 1024))).toBeNull();
    expect(issuesFor(synthesizeValues({ composition: undefined }))).toContain(
      "composition: Choose a composition HTML file.",
    );
  });

  it("flags a composition without scenes", () => {
    expect(issuesFor(synthesizeValues({ scenes: [] }))[0]).toContain("no scenes");
  });

  it("requires narration text, a voice and a text length within the limits", () => {
    const issues = issuesFor(
      synthesizeValues({
        voiceId: "",
        scenes: [
          { sceneId: "intro", text: "   " },
          { sceneId: "outro", text: "x".repeat(2001) },
        ],
      }),
    );

    expect(issues).toContain("voiceId: Choose a voice.");
    expect(issues).toContain("scenes.0.text: Enter the narration for this scene.");
    expect(issues).toContain("scenes.1.text: Use at most 2000 characters.");
  });

  it("limits the total narration length", () => {
    const scenes = Array.from({ length: 11 }, (_, index) => ({
      sceneId: `s${String(index)}`,
      text: "x".repeat(2000),
    }));

    expect(issuesFor(synthesizeValues({ scenes })).join(" ")).toContain(
      "20000 characters in total",
    );
  });

  it("requires an audio file per scene in upload mode and accepts text as optional", () => {
    const issues = issuesFor(
      synthesizeValues({
        mode: "upload",
        voiceId: "",
        scenes: [
          { sceneId: "intro", text: "" },
          {
            sceneId: "outro",
            text: "",
            audio: new File(["x"], "notes.txt", { type: "text/plain" }),
          },
        ],
      }),
    );

    expect(issues).toContain("scenes.0.audio: Choose an audio file for this scene.");
    expect(issues).toContain("scenes.1.audio: The file is not audio.");
    expect(audioFileError(new File(["x"], "a.mp3", { type: "audio/mpeg" }))).toBeNull();
  });

  it("limits aspects and the frame rate and ties burn-in to subtitles", () => {
    expect(issuesFor(synthesizeValues({ aspects: [] }))).toContain(
      "aspects: Choose at least one aspect ratio.",
    );
    expect(issuesFor(synthesizeValues({ fps: "23" }))).toContain(
      "fps: Enter a whole number from 24 to 60.",
    );
    expect(issuesFor(synthesizeValues({ fps: "61" }))).toHaveLength(1);
    expect(issuesFor(synthesizeValues({ fps: "24.5" }))).toHaveLength(1);
    expect(issuesFor(synthesizeValues({ fps: "60" }))).toEqual([]);
    expect(issuesFor(synthesizeValues({ subtitles: false, burnInSubtitles: true }))).toContain(
      "burnInSubtitles: Turn subtitles on to burn them in.",
    );
  });

  it("validates the golden form", () => {
    expect(goldenFormSchema.safeParse(emptyGoldenFormValues()).success).toBe(false);
    expect(
      goldenFormSchema.safeParse({ ...emptyGoldenFormValues(), voiceId: VOICE_ID }).success,
    ).toBe(true);
  });
});

describe("server-sent event parser", () => {
  const collect = (chunks: string[]): SseFrame[] => {
    const frames: SseFrame[] = [];
    const parser = createSseParser((frame) => frames.push(frame));
    for (const chunk of chunks) {
      parser.push(chunk);
    }
    parser.flush();
    return frames;
  };

  it("parses named events and ignores heartbeat comments", () => {
    expect(
      collect([
        'event: snapshot\ndata: {"a":1}\n\n',
        ": heartbeat\n\n",
        'event: progress\ndata: {"b":2}\n\n',
      ]),
    ).toEqual([
      { event: "snapshot", data: '{"a":1}' },
      { event: "progress", data: '{"b":2}' },
    ]);
  });

  it("reassembles frames split across chunks and handles CRLF and multi-line data", () => {
    expect(collect(["event: prog", "ress\r\ndata: one\r\ndata: two\r\n", "\r\n"])).toEqual([
      { event: "progress", data: "one\ntwo" },
    ]);
  });

  it("defaults the event name and drops frames without data", () => {
    expect(collect(["data: hi\n\n", "event: progress\n\n"])).toEqual([
      { event: "message", data: "hi" },
    ]);
  });
});

describe("progress reducer", () => {
  const event = (status: string, progress: number, extra: object = {}) => ({
    type: "event" as const,
    event: {
      renderId: RENDER_ID,
      status,
      stage: status === "queued" ? null : status,
      progress,
      at: "2026-10-20T10:00:00Z",
      ...extra,
    } as never,
  });

  it("tracks status, stage and progress and never lets progress go down", () => {
    let state = progressReducer(initialProgressState, event("capturing", 40));
    state = progressReducer(state, event("capturing", 25));

    expect(state).toMatchObject({ status: "capturing", stage: "capturing", progress: 40 });
    expect(state.terminal).toBe(false);
  });

  it("stops at the terminal state and keeps the error", () => {
    const failed = progressReducer(
      progressReducer(initialProgressState, event("capturing", 50)),
      event("failed", 55, { errorCode: "timeout", errorMessage: "Too slow" }),
    );
    const afterwards = progressReducer(failed, event("capturing", 90));

    expect(failed).toMatchObject({
      terminal: true,
      errorCode: "timeout",
      errorMessage: "Too slow",
    });
    expect(afterwards).toBe(failed);
    expect(progressReducer(initialProgressState, event("completed", 97)).progress).toBe(100);
  });

  it("moves from reconnecting to polling after repeated failures and resets on open", () => {
    let state = initialProgressState;
    expect(progressReducer(state, { type: "opened" }).connection).toBe("live");
    for (let failure = 1; failure < MAX_STREAM_ATTEMPTS; failure += 1) {
      state = progressReducer(state, { type: "failed" });
      expect(state.connection).toBe("reconnecting");
      expect(progressReducer(state, { type: "connecting" }).connection).toBe("reconnecting");
    }
    expect(progressReducer(state, { type: "opened" })).toMatchObject({
      connection: "live",
      failures: 0,
    });
    state = progressReducer(state, { type: "failed" });
    expect(state.connection).toBe("polling");
    expect(progressReducer(state, { type: "connecting" }).connection).toBe("polling");
  });

  it("backs off exponentially up to a ceiling", () => {
    expect([1, 2, 3, 4, 5, 6].map(reconnectDelayMs)).toEqual([
      1000, 2000, 4000, 8000, 15000, 15000,
    ]);
  });
});

describe("validation report parsing", () => {
  const report = {
    version: 1,
    valid: false,
    issues: [
      { code: "empty_scene", severity: "warning", kind: "layout", message: "Empty", timeMs: 100 },
      { code: "font_too_small", severity: "error", kind: "layout", message: "Small", timeMs: 1800 },
      {
        code: "text_overflow",
        severity: "error",
        kind: "layout",
        message: "Overflow",
        timeMs: 900,
      },
    ],
    stats: { scenes: 3 },
  };

  it("sorts errors before warnings and by time", () => {
    const parsed = parseValidationReport(report);

    expect(sortIssues(parsed?.issues ?? []).map((issue) => issue.code)).toEqual([
      "text_overflow",
      "font_too_small",
      "empty_scene",
    ]);
  });

  it("rejects malformed reports and timings", () => {
    expect(parseValidationReport(null)).toBeNull();
    expect(parseValidationReport({ valid: true })).toBeNull();
    expect(parseStageTimings("nope")).toEqual([]);
  });

  it("orders stage timings by pipeline order and ignores non-numbers", () => {
    expect(parseStageTimings({ encoding: 20, preparing: 5, extra: "x", capturing: 100 })).toEqual([
      { stage: "preparing", milliseconds: 5 },
      { stage: "capturing", milliseconds: 100 },
      { stage: "encoding", milliseconds: 20 },
    ]);
  });

  it("formats times as mm:ss.mmm", () => {
    expect(formatTimestampMs(0)).toBe("00:00.000");
    expect(formatTimestampMs(1800)).toBe("00:01.800");
    expect(formatTimestampMs(61_234)).toBe("01:01.234");
  });
});

describe("render guidance", () => {
  it("explains every deterministic failure code", () => {
    for (const code of [
      "network_violation",
      "timeout",
      "page_error",
      "invalid_composition",
      "validation_failed",
      "duration_limit_exceeded",
      "tts_failed",
      "output_check_failed",
      "render_stalled",
      "browser_crash",
      "insufficient_disk",
      "music_track_unavailable",
    ]) {
      expect(renderFailureGuidance[code]).toBeTruthy();
    }
    expect(renderFailureMessage("something_new")).toContain("not listed");
    expect(renderFailureMessage(null)).toContain("not listed");
  });

  it("maps creation problems to messages and uses the detail for rejected audio", () => {
    const problem = (code: string, status: number, detail: string | null = null) =>
      new ApiError({ kind: "http", status, code, title: code, detail });

    expect(adminRenderErrorMessage(problem("voice_not_available", 422))).toContain("not available");
    expect(
      adminRenderErrorMessage(
        problem("render_audio_rejected", 422, "The audio for scene intro was rejected."),
      ),
    ).toBe("The audio for scene intro was rejected.");
    expect(adminRenderErrorMessage(problem("anything", 413))).toContain("too large");
    expect(adminRenderErrorMessage(problem("composition_too_large", 413))).toContain("4 MB");
  });
});
