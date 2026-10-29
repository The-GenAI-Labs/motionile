import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { JobView } from "@/features/generation/components/job-view";
import { useJobUiStore } from "@/features/generation/store/job-ui.store";
import { ApiError } from "@/lib/api/api-error";

import {
  event,
  job,
  JOB_ID,
  RENDER_ID,
  storyboardView,
  styles,
  TOPIC_ID,
} from "./generation-fixtures";
import { rendition } from "./library-fixtures";
import { renderWithQuery } from "./render-with-query";

interface StreamOptions {
  onopen: (response: Response) => Promise<void>;
  onmessage: (message: { id: string; event: string; data: string }) => void;
}

const sse = vi.hoisted(() => ({
  options: null as StreamOptions | null,
  settle: null as { reject: (error: unknown) => void } | null,
  fetchEventSource: vi.fn(),
}));
const api = vi.hoisted(() => ({
  getJob: vi.fn(),
  getStoryboard: vi.fn(),
  cancelJob: vi.fn(),
  deleteJob: vi.fn(),
  reviseJob: vi.fn(),
  listStyles: vi.fn(),
  updateStoryboard: vi.fn(),
  approveJob: vi.fn(),
  regenerateStoryboard: vi.fn(),
}));
const libraryApi = vi.hoisted(() => ({ listRenditions: vi.fn() }));
const platformApi = vi.hoisted(() => ({ evaluatedFlags: vi.fn(), publicSettings: vi.fn() }));
const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));

vi.mock("@microsoft/fetch-event-source", () => ({ fetchEventSource: sse.fetchEventSource }));
vi.mock("@/features/generation/api/generation.api", () => api);
vi.mock("@/features/library/api/library.api", () => libraryApi);
vi.mock("@/features/platform/api/platform.api", () => platformApi);
vi.mock("next/navigation", () => ({ useRouter: () => router }));
vi.mock("@/features/library/components/render-player", () => ({
  RenderPlayer: ({ renderId }: { renderId: string }) => (
    <div role="region" aria-label="Video player">{`Player ${renderId}`}</div>
  ),
}));
vi.mock("@/features/library/components/share-link-dialog", () => ({
  ShareLinkDialog: ({ item }: { item: { jobId: string; renditions: unknown[] } }) => (
    <button type="button">{`Share ${String(item.renditions.length)} versions of ${item.jobId}`}</button>
  ),
}));
vi.mock("@/features/generation/components/lazy-storyboard-editor", async () => {
  const actual = await import("@/features/generation/components/storyboard-editor");
  return { LazyStoryboardEditor: actual.StoryboardEditor };
});

const portrait = rendition({
  id: "0197c5a2-1b2c-7d3e-8f40-5a6b7c8d9e11",
  aspect: "9:16",
  url: "https://cdn.motionile.test/9x16.mp4",
  subtitlesUrl: "https://cdn.motionile.test/9x16.vtt",
  subtitlesSrtUrl: "https://cdn.motionile.test/9x16.srt",
});

const completedJob = (overrides = {}) =>
  job({
    status: "completed",
    renderId: RENDER_ID,
    creditsCharged: 120,
    completedAt: "2026-10-25T10:10:00Z",
    currentStage: "render",
    ...overrides,
  });

const open = () => renderWithQuery(<JobView jobId={JOB_ID} />);

beforeEach(() => {
  vi.clearAllMocks();
  sse.options = null;
  useJobUiStore.getState().reset();
  sse.fetchEventSource.mockImplementation((_url: string, options: StreamOptions) => {
    sse.options = options;
    return new Promise<void>((_resolve, reject) => {
      sse.settle = { reject };
    });
  });
  api.getJob.mockResolvedValue(job());
  api.getStoryboard.mockResolvedValue(storyboardView());
  api.cancelJob.mockResolvedValue(job({ status: "cancelled" }));
  api.deleteJob.mockResolvedValue(undefined);
  api.reviseJob.mockResolvedValue(
    job({ id: "0197c5a2-1b2c-7d3e-8f40-5a6b7c8da099", parentJobId: JOB_ID }),
  );
  api.listStyles.mockResolvedValue({ items: styles });
  libraryApi.listRenditions.mockResolvedValue({ items: [rendition(), portrait] });
  platformApi.evaluatedFlags.mockResolvedValue({ flags: {} });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("JobView states", () => {
  it("shows a not found message for an unknown job", async () => {
    api.getJob.mockRejectedValue(
      new ApiError({
        kind: "http",
        status: 404,
        code: "job_not_found",
        title: "Missing",
        detail: null,
      }),
    );
    open();
    expect(await screen.findByText("We could not find that video.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to your library" })).toHaveAttribute(
      "href",
      "/library",
    );
  });

  it("shows the stage list for a queued or running job", async () => {
    api.getJob.mockResolvedValue(job({ status: "planning", currentStage: "plan" }));
    open();
    const list = await screen.findByRole("list", { name: "Video stages" });
    const items = within(list).getAllByRole("listitem");
    expect(items.length).toBeGreaterThanOrEqual(10);
    const planning = within(list).getByText("Planning the storyboard").closest("li");
    expect(planning).toHaveTextContent("In progress");
    expect(planning).toHaveAttribute("aria-current", "step");
    expect(screen.getByText("Safety check").closest("li")).toHaveTextContent("Done");
    expect(screen.getByText("Rendering video").closest("li")).toHaveTextContent("Waiting");
  });

  it("updates the timeline and the announcement from stream events", async () => {
    api.getJob.mockResolvedValue(job({ status: "planning", currentStage: "plan" }));
    open();
    await screen.findByRole("list", { name: "Video stages" });
    await waitFor(() => {
      expect(sse.options).not.toBeNull();
    });
    await act(async () => {
      await sse.options?.onopen(
        new Response(null, { status: 200, headers: { "content-type": "text/event-stream" } }),
      );
      const started = event("stage.started", { stage: "voice" }, 1, "voice");
      sse.options?.onmessage({
        id: started.id ?? "",
        event: "job_event",
        data: JSON.stringify(started),
      });
      const voiced = event("scene.voiced", { sceneId: "s1" }, 2);
      sse.options?.onmessage({
        id: voiced.id ?? "",
        event: "job_event",
        data: JSON.stringify(voiced),
      });
    });
    const row = within(screen.getByRole("list", { name: "Video stages" }))
      .getByText("Recording narration")
      .closest("li");
    expect(row).toHaveTextContent("In progress");
    expect(row).toHaveTextContent("1 scene voiced");
    expect(screen.getByText("Live updates connected")).toBeInTheDocument();
    expect(
      screen
        .getAllByRole("status")
        .some((node) => node.textContent.startsWith("Recording narration.")),
    ).toBe(true);
  });

  it("shows render progress as a progress bar", async () => {
    api.getJob.mockResolvedValue(job({ status: "rendering", currentStage: "render" }));
    open();
    await screen.findByRole("list", { name: "Video stages" });
    await waitFor(() => {
      expect(sse.options).not.toBeNull();
    });
    act(() => {
      const progress = {
        ...event("render.progress", { renderId: RENDER_ID, progress: 55 }),
        id: null,
      };
      sse.options?.onmessage({ id: "", event: "job_event", data: JSON.stringify(progress) });
    });
    await waitFor(() => {
      expect(screen.getByRole("progressbar", { name: "Render progress" })).toHaveAttribute(
        "aria-valuenow",
        "55",
      );
    });
  });

  it("cancels a running video after confirmation and mentions the returned credits", async () => {
    const user = userEvent.setup();
    api.getJob.mockResolvedValue(job({ status: "voicing", currentStage: "voice" }));
    open();
    await user.click(await screen.findByRole("button", { name: "Cancel video" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("140 credits held for this video are returned");
    await user.click(within(dialog).getByRole("button", { name: "Cancel video" }));
    await waitFor(() => {
      expect(api.cancelJob).toHaveBeenCalledWith(JOB_ID);
    });
  });

  it("shows the storyboard editor while the job awaits approval", async () => {
    api.getJob.mockResolvedValue(job({ status: "awaiting_approval", currentStage: "approval" }));
    open();
    expect(
      await screen.findByRole("heading", { name: "Review the storyboard" }),
    ).toBeInTheDocument();
    expect(await screen.findByRole("form", { name: "Storyboard editor" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve and continue" })).toBeEnabled();
  });

  it("falls back to polling after the stream keeps failing", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    api.getJob.mockResolvedValue(job({ status: "voicing", currentStage: "voice" }));
    open();
    await screen.findByRole("list", { name: "Video stages" });
    await waitFor(() => {
      expect(sse.settle).not.toBeNull();
    });
    act(() => {
      sse.settle?.reject(new TypeError("offline"));
    });
    expect(
      await screen.findByText(/Live updates unavailable. Checking every 3 seconds/),
    ).toBeInTheDocument();
    const before = api.getJob.mock.calls.length;
    api.getJob.mockResolvedValue(completedJob());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3100);
    });
    await waitFor(() => {
      expect(api.getJob.mock.calls.length).toBeGreaterThan(before);
    });
    expect(await screen.findByRole("region", { name: "Video player" })).toBeInTheDocument();
  });
});

describe("completed job", () => {
  beforeEach(() => {
    api.getJob.mockResolvedValue(completedJob({ fallbackSceneIds: ["s2"] }));
  });

  it("plays the render and offers a download per aspect with subtitle files", async () => {
    open();
    expect(await screen.findByRole("region", { name: "Video player" })).toHaveTextContent(
      `Player ${RENDER_ID}`,
    );
    const landscape = await screen.findByRole("link", { name: "Download 16:9 landscape video" });
    expect(landscape).toHaveAttribute(
      "href",
      "https://cdn.motionile.test/media/u/u1/renders/r1/16x9.mp4",
    );
    expect(screen.getByRole("link", { name: "Download 9:16 portrait video" })).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Download 16:9 landscape subtitles as VTT" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Download 9:16 portrait subtitles as SRT" }),
    ).toHaveAttribute("href", "https://cdn.motionile.test/9x16.srt");
    expect(screen.getByText("120 credits charged, 20 returned")).toBeInTheDocument();
  });

  it("explains which scenes used a simple layout", async () => {
    open();
    expect(
      await screen.findByText("Scene 2 used a simple text layout: Goal 2."),
    ).toBeInTheDocument();
  });

  it("passes the finished renditions to the share dialog", async () => {
    open();
    expect(
      await screen.findByRole("button", { name: `Share 2 versions of ${JOB_ID}` }),
    ).toBeInTheDocument();
  });

  it("hides the publish action while the flag is off and shows it when on", async () => {
    const first = open();
    await screen.findByRole("button", { name: "Revise" });
    expect(screen.queryByRole("link", { name: "Publish" })).not.toBeInTheDocument();
    first.unmount();
    platformApi.evaluatedFlags.mockResolvedValue({ flags: { "publishing.enabled": true } });
    open();
    expect(await screen.findByRole("link", { name: "Publish" })).toHaveAttribute(
      "href",
      `/publish?job=${JOB_ID}`,
    );
  });

  it("starts a revision and opens the child job", async () => {
    const user = userEvent.setup();
    open();
    await user.click(await screen.findByRole("button", { name: "Revise" }));
    await user.click(await screen.findByRole("button", { name: "Start revision" }));
    expect(await screen.findByText("Tell Motionile what to change.")).toBeInTheDocument();
    await user.type(screen.getByRole("textbox", { name: "What should change?" }), "Slow it down");
    await user.click(await screen.findByRole("checkbox", { name: "Scene 2: Goal 2" }));
    await user.click(screen.getByRole("switch", { name: "Change the length" }));
    const length = screen.getByRole("spinbutton", { name: "New length in seconds" });
    await user.clear(length);
    await user.type(length, "90");
    await user.click(screen.getByRole("button", { name: "Start revision" }));
    await waitFor(() => {
      expect(api.reviseJob).toHaveBeenCalledTimes(1);
    });
    const [jobId, input] = api.reviseJob.mock.calls[0] as [
      string,
      { body: unknown; idempotencyKey: string },
    ];
    expect(jobId).toBe(JOB_ID);
    expect(input.body).toEqual({
      instructions: "Slow it down",
      sceneIds: ["s2"],
      options: { durationSeconds: 90 },
    });
    expect(input.idempotencyKey).toBeTruthy();
    await waitFor(() => {
      expect(router.push).toHaveBeenCalledWith("/jobs/0197c5a2-1b2c-7d3e-8f40-5a6b7c8da099");
    });
  });

  it("deletes the video after confirmation and returns to the library", async () => {
    const user = userEvent.setup();
    open();
    await user.click(await screen.findByRole("button", { name: "Delete" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete video" }));
    await waitFor(() => {
      expect(api.deleteJob).toHaveBeenCalledWith(JOB_ID);
    });
    expect(router.push).toHaveBeenCalledWith("/library");
  });
});

describe("failed and cancelled jobs", () => {
  it("shows the policy message and offers to try again with the question", async () => {
    api.getJob.mockResolvedValue(
      job({
        status: "failed",
        errorCode: "policy_weapons",
        errorTitle: "Request not supported",
        errorMessage: "Motionile cannot make videos that explain how to build or use weapons.",
      }),
    );
    open();
    expect(
      await screen.findByRole("heading", { name: "Request not supported" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/cannot make videos that explain how to build or use weapons/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/140 credits were held for this video and have been returned/),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Try again" })).toHaveAttribute(
      "href",
      `/create?query=${encodeURIComponent("How does a hash map work?")}`,
    );
  });

  it("links back to the topic for a catalog job", async () => {
    api.getJob.mockResolvedValue(
      job({
        status: "failed",
        source: "catalog",
        topicId: TOPIC_ID,
        errorCode: "tts_failed",
        errorMessage: null,
      }),
    );
    open();
    expect(await screen.findByText(/Narration could not be recorded/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Try again" })).toHaveAttribute(
      "href",
      `/create?topic=${TOPIC_ID}`,
    );
  });

  it("explains a cancelled video", async () => {
    api.getJob.mockResolvedValue(job({ status: "cancelled", errorCode: "user_cancelled" }));
    open();
    expect(await screen.findByRole("heading", { name: "Video cancelled" })).toBeInTheDocument();
    expect(
      screen.getByText("You cancelled this video. Your credits were returned."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel video" })).not.toBeInTheDocument();
  });
});
