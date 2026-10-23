import { QueryClientProvider } from "@tanstack/react-query";
import { renderHook, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type * as AdminRenderApi from "@/features/admin-render/api/admin-render.api";
import { FailurePanel } from "@/features/admin-render/components/failure-panel";
import { GoldenList } from "@/features/admin-render/components/golden-list";
import { ProgressPanel } from "@/features/admin-render/components/progress-panel";
import { RenderMonitor } from "@/features/admin-render/components/render-monitor";
import { TimingsTable } from "@/features/admin-render/components/timings-table";
import { UploadRenderForm } from "@/features/admin-render/components/upload-render-form";
import { ValidationReport } from "@/features/admin-render/components/validation-report";
import { useRenderEvents } from "@/features/admin-render/hooks/use-render-events";
import {
  parseStageTimings,
  parseValidationReport,
} from "@/features/admin-render/schemas/admin-render.schema";
import { ApiError } from "@/lib/api/api-error";

import {
  BED_MUSIC_ID,
  BED_VOICE_ID,
  bedMusic,
  completedBed,
  failedBed,
  goldenCatalog,
  RENDER_ID,
  renderBed,
} from "./admin-render-fixtures";
import { makeTestQueryClient, renderWithQuery } from "./render-with-query";
import { nth } from "./test-helpers";
import { voice } from "./voices-fixtures";

const api = vi.hoisted(() => ({
  createTestbedRender: vi.fn(),
  listGoldenCompositions: vi.fn(),
  createGoldenRender: vi.fn(),
  listBedMusicTracks: vi.fn(),
  getTestbedRender: vi.fn(),
  cancelTestbedRender: vi.fn(),
  streamRenderEvents: vi.fn(),
}));
const voicesApi = vi.hoisted(() => ({ listVoices: vi.fn() }));
const navigation = vi.hoisted(() => ({ push: vi.fn() }));

vi.mock("@/features/admin-render/api/admin-render.api", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  ...api,
}));
vi.mock("@/features/voices/api/voices.api", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  ...voicesApi,
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: navigation.push }),
}));
vi.mock("@/features/library/components/render-player", () => ({
  RenderPlayer: ({ renderId }: { renderId: string }) => (
    <div role="region" aria-label={`Player for ${renderId}`} />
  ),
}));

const problem = (code: string, status: number, detail: string | null = null) =>
  new ApiError({ kind: "http", status, code, title: code, detail });

beforeEach(() => {
  vi.clearAllMocks();
  voicesApi.listVoices.mockResolvedValue({
    items: [voice({ id: BED_VOICE_ID, name: "Aria" })],
    nextCursor: null,
  });
  api.listBedMusicTracks.mockResolvedValue(bedMusic);
  api.listGoldenCompositions.mockResolvedValue(goldenCatalog);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("validation report", () => {
  it("lists errors before warnings with every column", () => {
    renderWithQuery(
      <ValidationReport report={parseValidationReport(failedBed.validationReport)} />,
    );

    const table = screen.getByRole("table", { name: "Validation issues, errors first" });
    const headers = within(table)
      .getAllByRole("columnheader")
      .map((header) => header.textContent);
    const rows = within(table).getAllByRole("row").slice(1);

    expect(headers).toEqual(["Severity", "Code", "Message", "Scene", "Time", "Aspect", "Selector"]);
    expect(within(nth(rows, 0)).getByText("Error")).toBeInTheDocument();
    expect(within(nth(rows, 0)).getByText("font_too_small")).toBeInTheDocument();
    expect(within(nth(rows, 0)).getByText("00:01.800")).toBeInTheDocument();
    expect(within(nth(rows, 0)).getByText("#footnote")).toBeInTheDocument();
    expect(within(nth(rows, 0)).getByText("9:16")).toBeInTheDocument();
    expect(within(nth(rows, 1)).getByText("Warning")).toBeInTheDocument();
    expect(screen.getByText(/1 error, 1 warning\. Errors block the render\./)).toBeInTheDocument();
  });

  it("shows an empty state for a valid composition and nothing without a report", () => {
    const { unmount } = renderWithQuery(
      <ValidationReport report={parseValidationReport(completedBed.validationReport)} />,
    );

    expect(screen.getByRole("status")).toHaveTextContent("No issues found");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    unmount();
    renderWithQuery(<ValidationReport report={null} />);
    expect(screen.queryByRole("heading")).not.toBeInTheDocument();
  });
});

describe("progress and timings", () => {
  it("shows the bar, the current stage and the finished stages", () => {
    renderWithQuery(
      <ProgressPanel status="capturing" stage="capturing" progress={40} connection="live" />,
    );

    expect(screen.getByRole("progressbar", { name: "Render progress" })).toHaveAttribute(
      "aria-valuenow",
      "40",
    );
    expect(screen.getByRole("progressbar")).toHaveAttribute(
      "aria-valuetext",
      "Capturing frames, 40 percent",
    );
    const stages = within(screen.getByRole("list", { name: "Render stages" })).getAllByRole(
      "listitem",
    );
    expect(stages).toHaveLength(6);
    expect(stages[0]).toHaveTextContent("Preparing (done)");
    expect(stages[3]).toHaveAttribute("aria-current", "step");
    expect(stages[3]).toHaveTextContent("Capturing frames (current)");
    expect(stages[5]).toHaveTextContent("Finalizing (waiting)");
    expect(screen.getByText("Live updates connected")).toBeInTheDocument();
  });

  it("describes a lost connection and the polling fallback", () => {
    const { rerender } = renderWithQuery(
      <ProgressPanel status="queued" stage={null} progress={0} connection="reconnecting" />,
    );

    expect(screen.getByText("Live updates lost. Reconnecting")).toBeInTheDocument();
    rerender(<ProgressPanel status="queued" stage={null} progress={0} connection="polling" />);
    expect(screen.getByText(/checking every 3 seconds/i)).toBeInTheDocument();
  });

  it("tabulates the stage timings with a total", () => {
    renderWithQuery(
      <TimingsTable timings={parseStageTimings({ preparing: 1200, voicing: 4100 })} />,
    );

    const table = screen.getByRole("table", { name: "Time spent in each render stage" });

    expect(within(table).getByRole("row", { name: /Preparing/ })).toHaveTextContent("1.2 s");
    expect(within(table).getByRole("row", { name: /Total/ })).toHaveTextContent("5.3 s");
  });
});

describe("failure panel", () => {
  it("shows the code, the message and guidance for the code", () => {
    renderWithQuery(
      <FailurePanel
        status="failed"
        errorCode="network_violation"
        errorMessage="Blocked https://example.com"
      />,
    );

    expect(screen.getByRole("heading", { name: "Render failed" })).toBeInTheDocument();
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("network_violation");
    expect(alert).toHaveTextContent("Blocked https://example.com");
    expect(alert).toHaveTextContent("must be self-contained");
  });

  it("reports a cancelled render and renders nothing for other states", () => {
    const { rerender } = renderWithQuery(
      <FailurePanel status="cancelled" errorCode={null} errorMessage={null} />,
    );

    expect(screen.getByRole("heading", { name: "Render cancelled" })).toBeInTheDocument();
    rerender(<FailurePanel status="capturing" errorCode={null} errorMessage={null} />);
    expect(screen.queryByRole("heading")).not.toBeInTheDocument();
  });
});

describe("render events hook", () => {
  const wrapperFor = (client = makeTestQueryClient()) => {
    const Wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    return Wrapper;
  };
  const progressEvent = (status: string, progress: number, extra: object = {}) => ({
    renderId: RENDER_ID,
    status,
    stage: status === "capturing" ? "capturing" : null,
    progress,
    at: "2026-10-20T10:00:00Z",
    ...extra,
  });
  const instantDelay = () => Promise.resolve();

  it("applies stream events and stops at the terminal state", async () => {
    const stream = vi.fn(
      (_id: string, handlers: { onOpen: () => void; onEvent: (e: never) => void }) => {
        handlers.onOpen();
        handlers.onEvent(progressEvent("capturing", 30) as never);
        handlers.onEvent(progressEvent("completed", 100) as never);
        return Promise.resolve(true);
      },
    );
    const client = makeTestQueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(
      () => useRenderEvents(RENDER_ID, { enabled: true, stream: stream, delay: instantDelay }),
      { wrapper: wrapperFor(client) },
    );

    await waitFor(() => {
      expect(result.current.terminal).toBe(true);
    });
    expect(result.current).toMatchObject({
      status: "completed",
      progress: 100,
      connection: "live",
    });
    expect(stream).toHaveBeenCalledTimes(1);
    await waitFor(() => {
      expect(invalidate).toHaveBeenCalled();
    });
  });

  it("reconnects after a failure and recovers", async () => {
    const stream = vi
      .fn()
      .mockRejectedValueOnce(new Error("network"))
      .mockImplementationOnce(
        (_id: string, handlers: { onOpen: () => void; onEvent: (e: never) => void }) => {
          handlers.onOpen();
          handlers.onEvent(progressEvent("failed", 60, { errorCode: "timeout" }) as never);
          return Promise.resolve(true);
        },
      );
    const { result } = renderHook(
      () =>
        useRenderEvents(RENDER_ID, { enabled: true, stream: stream as never, delay: instantDelay }),
      { wrapper: wrapperFor() },
    );

    await waitFor(() => {
      expect(result.current.terminal).toBe(true);
    });
    expect(stream).toHaveBeenCalledTimes(2);
    expect(result.current).toMatchObject({ status: "failed", errorCode: "timeout", failures: 0 });
  });

  it("falls back to polling after repeated failures and stops trying", async () => {
    const stream = vi.fn().mockRejectedValue(new Error("down"));
    const { result } = renderHook(
      () =>
        useRenderEvents(RENDER_ID, { enabled: true, stream: stream as never, delay: instantDelay }),
      { wrapper: wrapperFor() },
    );

    await waitFor(() => {
      expect(result.current.connection).toBe("polling");
    });
    expect(stream).toHaveBeenCalledTimes(4);
    expect(result.current.terminal).toBe(false);
  });

  it("does not connect when disabled and aborts when unmounted", async () => {
    const stream = vi.fn();
    const disabled = renderHook(
      () =>
        useRenderEvents(RENDER_ID, {
          enabled: false,
          stream: stream as never,
          delay: instantDelay,
        }),
      { wrapper: wrapperFor() },
    );
    expect(stream).not.toHaveBeenCalled();
    disabled.unmount();

    let signal: AbortSignal | undefined;
    const pending = vi.fn(
      (_id: string, handlers: { signal: AbortSignal }) =>
        new Promise<boolean>(() => {
          signal = handlers.signal;
        }),
    );
    const live = renderHook(
      () =>
        useRenderEvents(RENDER_ID, {
          enabled: true,
          stream: pending,
          delay: instantDelay,
        }),
      { wrapper: wrapperFor() },
    );
    await waitFor(() => {
      expect(signal).toBeDefined();
    });
    live.unmount();
    expect(signal?.aborted).toBe(true);
  });
});

describe("render monitor", () => {
  it("shows live progress from the stream while the render is active", async () => {
    api.getTestbedRender.mockResolvedValue(renderBed());
    api.streamRenderEvents.mockImplementation(
      async (_id: string, handlers: { onOpen: () => void; onEvent: (e: never) => void }) => {
        handlers.onOpen();
        handlers.onEvent({
          renderId: RENDER_ID,
          status: "encoding",
          stage: "encoding",
          progress: 88,
          at: "2026-10-20T10:01:00Z",
        } as never);
        return new Promise<boolean>(() => undefined);
      },
    );
    renderWithQuery(<RenderMonitor renderId={RENDER_ID} />);

    const bar = await screen.findByRole("progressbar", { name: "Render progress" });
    await waitFor(() => {
      expect(bar).toHaveAttribute("aria-valuenow", "88");
    });
    expect(screen.getByRole("button", { name: "Cancel render" })).toBeInTheDocument();
    expect(screen.getByText("Live updates connected")).toBeInTheDocument();
    expect(
      screen.getByRole("table", { name: "Time spent in each render stage" }),
    ).toBeInTheDocument();
  });

  it("confirms before cancelling and sends the cancel request", async () => {
    api.getTestbedRender.mockResolvedValue(renderBed());
    api.streamRenderEvents.mockReturnValue(new Promise<boolean>(() => undefined));
    api.cancelTestbedRender.mockResolvedValue(renderBed({ status: "cancelled" }));
    const user = userEvent.setup();
    renderWithQuery(<RenderMonitor renderId={RENDER_ID} />);

    await user.click(await screen.findByRole("button", { name: "Cancel render" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Cancel this render?" });
    expect(api.cancelTestbedRender).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "Cancel render" }));

    await waitFor(() => {
      expect(api.cancelTestbedRender).toHaveBeenCalledWith(RENDER_ID);
    });
  });

  it("shows the failure, its guidance and the report for a failed render", async () => {
    api.getTestbedRender.mockResolvedValue(failedBed);
    renderWithQuery(<RenderMonitor renderId={RENDER_ID} />);

    expect(await screen.findByRole("heading", { name: "Render failed" })).toBeInTheDocument();
    expect(screen.getByText(/layout or timing errors/)).toBeInTheDocument();
    expect(
      screen.getByRole("table", { name: "Validation issues, errors first" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel render" })).not.toBeInTheDocument();
    expect(api.streamRenderEvents).not.toHaveBeenCalled();
  });

  it("plays the result and links the subtitle files for a completed render", async () => {
    api.getTestbedRender.mockResolvedValue(completedBed);
    renderWithQuery(<RenderMonitor renderId={RENDER_ID} />);

    expect(
      await screen.findByRole("region", { name: `Player for ${RENDER_ID}` }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download WebVTT subtitles" })).toHaveAttribute(
      "href",
      "https://cdn.motionile.test/subtitles.vtt",
    );
    expect(screen.getByRole("link", { name: "Download SRT subtitles" })).toHaveAttribute(
      "href",
      "https://cdn.motionile.test/subtitles.srt",
    );
    expect(screen.getByRole("link", { name: "Open poster frame for 16:9" })).toBeInTheDocument();
  });

  it("explains a render that cannot be loaded and retries", async () => {
    api.getTestbedRender.mockRejectedValueOnce(problem("render_not_found", 404));
    api.getTestbedRender.mockResolvedValueOnce(failedBed);
    const user = userEvent.setup();
    renderWithQuery(<RenderMonitor renderId={RENDER_ID} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("does not exist");
    await user.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("heading", { name: "Render failed" })).toBeInTheDocument();
  });
});

const compositionHtml = (ids: string[]) =>
  new File(
    [
      `<html><body>${ids.map((id) => `<section data-scene="${id}"></section>`).join("")}</body></html>`,
    ],
    "demo.html",
    {
      type: "text/html",
    },
  );

describe("upload render form", () => {
  it("reads the scenes from the composition and labels a narration field per scene", async () => {
    const user = userEvent.setup();
    renderWithQuery(<UploadRenderForm />);

    await user.upload(
      screen.getByLabelText("Composition HTML file"),
      compositionHtml(["intro", "outro"]),
    );

    const first = await screen.findByLabelText("Narration for scene intro");
    expect(screen.getByLabelText("Narration for scene outro")).toBeInTheDocument();
    await user.type(first, "Hello");
    expect(screen.getAllByText("5 / 2000 characters")).toHaveLength(1);
    expect(screen.getByText("0 / 2000 characters")).toBeInTheDocument();
  });

  it("rejects a file that is not html before reading it", async () => {
    const user = userEvent.setup({ applyAccept: false });
    renderWithQuery(<UploadRenderForm />);

    await user.upload(
      screen.getByLabelText("Composition HTML file"),
      new File(["x"], "notes.txt", { type: "text/plain" }),
    );

    expect(await screen.findByText("The composition must be an .html file.")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Scene narration" })).not.toBeInTheDocument();
  });

  it("disables burn-in until subtitles are on", async () => {
    const user = userEvent.setup();
    renderWithQuery(<UploadRenderForm />);
    const subtitles = screen.getByRole("switch", { name: "Subtitles" });
    const burnIn = screen.getByRole("switch", { name: "Burn subtitles into the video" });

    expect(burnIn).toBeEnabled();
    await user.click(burnIn);
    expect(burnIn).toBeChecked();
    await user.click(subtitles);
    expect(burnIn).toBeDisabled();
    expect(burnIn).not.toBeChecked();
  });

  it("requires at least one aspect and a valid frame rate", async () => {
    const user = userEvent.setup();
    renderWithQuery(<UploadRenderForm />);

    for (const name of ["16:9 landscape", "9:16 portrait", "1:1 square"]) {
      await user.click(screen.getByRole("checkbox", { name }));
    }
    const fps = screen.getByRole("spinbutton", { name: "Frame rate (fps)" });
    expect(fps).toHaveValue(30);
    await user.clear(fps);
    await user.type(fps, "99");
    await user.click(screen.getByRole("button", { name: "Start render" }));

    expect(await screen.findByText("Choose at least one aspect ratio.")).toBeInTheDocument();
    expect(screen.getByText("Enter a whole number from 24 to 60.")).toBeInTheDocument();
    expect(api.createTestbedRender).not.toHaveBeenCalled();
  });

  it("submits the multipart request and opens the render page", async () => {
    api.createTestbedRender.mockResolvedValue(renderBed({ status: "queued" }));
    const user = userEvent.setup();
    renderWithQuery(<UploadRenderForm />);

    await user.upload(screen.getByLabelText("Composition HTML file"), compositionHtml(["intro"]));
    await user.type(
      await screen.findByLabelText("Narration for scene intro"),
      "Welcome to the show.",
    );
    await user.selectOptions(await screen.findByRole("combobox", { name: "Voice" }), BED_VOICE_ID);
    await user.selectOptions(
      await screen.findByRole("combobox", { name: "Music track" }),
      BED_MUSIC_ID,
    );
    await user.click(screen.getByRole("button", { name: "Start render" }));

    await waitFor(() => {
      expect(api.createTestbedRender).toHaveBeenCalledTimes(1);
    });
    const body = api.createTestbedRender.mock.calls[0]?.[0] as FormData;
    expect((body.get("composition") as File).name).toBe("demo.html");
    expect(JSON.parse(body.get("options") as string)).toMatchObject({
      fps: 30,
      musicTrackId: BED_MUSIC_ID,
      narration: {
        mode: "synthesize",
        voiceId: BED_VOICE_ID,
        scenes: [{ sceneId: "intro", text: "Welcome to the show." }],
      },
    });
    await waitFor(() => {
      expect(navigation.push).toHaveBeenCalledWith(`/admin/render/${RENDER_ID}`);
    });
  });

  it("offers one audio input per scene in upload mode and sends the audio parts", async () => {
    api.createTestbedRender.mockResolvedValue(renderBed({ status: "queued" }));
    const user = userEvent.setup();
    renderWithQuery(<UploadRenderForm />);

    await user.upload(
      screen.getByLabelText("Composition HTML file"),
      compositionHtml(["intro", "outro"]),
    );
    await screen.findByLabelText("Narration for scene intro");
    await user.click(screen.getByRole("radio", { name: "Upload audio" }));
    await user.upload(
      await screen.findByLabelText("Audio for scene intro"),
      new File(["a"], "intro.mp3", { type: "audio/mpeg" }),
    );
    await user.upload(
      screen.getByLabelText("Audio for scene outro"),
      new File(["b"], "outro.mp3", { type: "audio/mpeg" }),
    );
    expect(screen.getByLabelText("Text for scene intro (optional)")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Voice" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Start render" }));

    await waitFor(() => {
      expect(api.createTestbedRender).toHaveBeenCalledTimes(1);
    });
    const body = api.createTestbedRender.mock.calls[0]?.[0] as FormData;
    expect([...body.keys()].toSorted()).toEqual(["audio-0", "audio-1", "composition", "options"]);
  });

  it("maps a server problem code to a message and keeps the form", async () => {
    api.createTestbedRender.mockRejectedValue(problem("composition_too_large", 413));
    const user = userEvent.setup();
    renderWithQuery(<UploadRenderForm />);

    await user.upload(screen.getByLabelText("Composition HTML file"), compositionHtml(["intro"]));
    await user.type(await screen.findByLabelText("Narration for scene intro"), "Words.");
    await user.selectOptions(await screen.findByRole("combobox", { name: "Voice" }), BED_VOICE_ID);
    await user.click(screen.getByRole("button", { name: "Start render" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("larger than 4 MB");
    expect(navigation.push).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Start render" })).toBeEnabled();
  });
});

describe("golden compositions", () => {
  it("lists each composition with its description and scene ids", async () => {
    renderWithQuery(<GoldenList />);

    const list = await screen.findByRole("list", { name: "Golden compositions" });
    const items = within(list).getAllByRole("listitem");

    expect(items).toHaveLength(2);
    expect(
      within(nth(items, 0)).getByRole("heading", { name: "Flow diagram" }),
    ).toBeInTheDocument();
    expect(items[0]).toHaveTextContent("intro, steps");
    expect(
      within(nth(items, 0)).getByRole("button", { name: "Render Flow diagram" }),
    ).toBeInTheDocument();
  });

  it("opens the options form and renders the golden composition", async () => {
    api.createGoldenRender.mockResolvedValue(renderBed({ status: "queued" }));
    const user = userEvent.setup();
    renderWithQuery(<GoldenList />);

    await user.click(await screen.findByRole("button", { name: "Render Flow diagram" }));
    const dialog = await screen.findByRole("dialog", { name: "Render Flow diagram" });
    await user.selectOptions(
      await within(dialog).findByRole("combobox", { name: "Voice" }),
      BED_VOICE_ID,
    );
    await user.click(within(dialog).getByRole("checkbox", { name: "1:1 square" }));
    await user.click(within(dialog).getByRole("button", { name: "Start render" }));

    await waitFor(() => {
      expect(api.createGoldenRender).toHaveBeenCalledWith("flow-diagram", {
        voiceId: BED_VOICE_ID,
        aspects: ["16:9", "9:16"],
        fps: 30,
        musicTrackId: null,
        subtitles: true,
        burnInSubtitles: false,
      });
    });
    await waitFor(() => {
      expect(navigation.push).toHaveBeenCalledWith(`/admin/render/${RENDER_ID}`);
    });
  });

  it("requires a voice and reports a server problem", async () => {
    api.createGoldenRender.mockRejectedValue(problem("voice_not_available", 422));
    const user = userEvent.setup();
    renderWithQuery(<GoldenList />);

    await user.click(await screen.findByRole("button", { name: "Render Kinetic typography" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Start render" }));
    expect(await within(dialog).findByText("Choose a voice.")).toBeInTheDocument();
    await user.selectOptions(
      await within(dialog).findByRole("combobox", { name: "Voice" }),
      BED_VOICE_ID,
    );
    await user.click(within(dialog).getByRole("button", { name: "Start render" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent("not available");
  });

  it("shows an error with retry when the catalog cannot be loaded", async () => {
    api.listGoldenCompositions.mockRejectedValueOnce(problem("forbidden", 403));
    const user = userEvent.setup();
    renderWithQuery(<GoldenList />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "not allowed to use the render test bed",
    );
    await user.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("list", { name: "Golden compositions" })).toBeInTheDocument();
  });
});

describe("render stream client", () => {
  it("parses snapshot and progress frames from a response body and reports the terminal state", async () => {
    const { streamRenderEvents } = await vi.importActual<typeof AdminRenderApi>(
      "@/features/admin-render/api/admin-render.api",
    );
    const frame = (event: string, status: string, progress: number) =>
      `event: ${event}\ndata: ${JSON.stringify({ renderId: RENDER_ID, status, progress, at: "2026-10-20T10:00:00Z" })}\n\n`;
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode(frame("snapshot", "queued", 0)));
        controller.enqueue(encoder.encode(": heartbeat\n\n"));
        controller.enqueue(encoder.encode(frame("progress", "completed", 100).slice(0, 20)));
        controller.enqueue(encoder.encode(frame("progress", "completed", 100).slice(20)));
        controller.close();
      },
    });
    const fetchImpl = vi.fn().mockResolvedValue(new Response(body, { status: 200 }));
    const events: string[] = [];
    const onOpen = vi.fn();

    const terminal = await streamRenderEvents(RENDER_ID, {
      signal: new AbortController().signal,
      onOpen,
      onEvent: (event) => events.push(`${event.status}:${String(event.progress)}`),
      fetchImpl: fetchImpl as never,
    });

    expect(terminal).toBe(true);
    expect(events).toEqual(["queued:0", "completed:100"]);
    expect(onOpen).toHaveBeenCalledTimes(1);
    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(new RegExp(`/v1/admin/render/testbed/${RENDER_ID}/events$`));
    expect(init).toMatchObject({
      credentials: "include",
      headers: { Accept: "text/event-stream" },
    });
  });

  it("throws a normalized error for a failed response", async () => {
    const { streamRenderEvents } = await vi.importActual<typeof AdminRenderApi>(
      "@/features/admin-render/api/admin-render.api",
    );
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          type: "urn:motionile:problem:render_not_found",
          title: "Not found",
          status: 404,
          code: "render_not_found",
        }),
        { status: 404, headers: { "Content-Type": "application/problem+json" } },
      ),
    );

    await expect(
      streamRenderEvents(RENDER_ID, {
        signal: new AbortController().signal,
        onOpen: vi.fn(),
        onEvent: vi.fn(),
        fetchImpl: fetchImpl as never,
      }),
    ).rejects.toMatchObject({ code: "render_not_found", status: 404 });
  });
});
