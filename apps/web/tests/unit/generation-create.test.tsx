import { QueryClientProvider } from "@tanstack/react-query";
import { renderHook, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, type MockInstance, vi } from "vitest";

import { CreateVideoForm } from "@/features/generation/components/create-video-form";
import { useJobEstimate } from "@/features/generation/hooks/use-job-estimate";
import { ApiError } from "@/lib/api/api-error";

import {
  CLONED_VOICE_ID,
  estimateView,
  job,
  JOB_ID,
  styles,
  TOPIC_ID,
  VOICE_ID,
} from "./generation-fixtures";
import { makeTestQueryClient, renderWithQuery } from "./render-with-query";

const api = vi.hoisted(() => ({
  listStyles: vi.fn(),
  estimateJob: vi.fn(),
  createJob: vi.fn(),
}));
const topicApi = vi.hoisted(() => ({ resolveTopicReference: vi.fn() }));
const usersApi = vi.hoisted(() => ({ userPreferences: vi.fn() }));
const platformApi = vi.hoisted(() => ({ publicSettings: vi.fn(), evaluatedFlags: vi.fn() }));
const creditsApi = vi.hoisted(() => ({ getWallet: vi.fn() }));
const voicesApi = vi.hoisted(() => ({ listVoices: vi.fn() }));
const catalogApi = vi.hoisted(() => ({ searchCatalog: vi.fn() }));
const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));

vi.mock("@/features/generation/api/generation.api", () => api);
vi.mock("@/features/generation/api/topic-reference.api", () => topicApi);
vi.mock("@/features/users/api/users.api", () => usersApi);
vi.mock("@/features/platform/api/platform.api", () => platformApi);
vi.mock("@/features/credits/api/credits.api", () => creditsApi);
vi.mock("@/features/voices/api/voices.api", () => voicesApi);
vi.mock("@/features/catalog/api/catalog.api", () => catalogApi);
vi.mock("next/navigation", () => ({ useRouter: () => router }));

const KEY_ONE = "11111111-1111-4111-8111-111111111111";
const KEY_TWO = "22222222-2222-4222-8222-222222222222";
const KEY_THREE = "33333333-3333-4333-8333-333333333333";

const voice = (id: string, kind: "builtin" | "cloned", name: string) => ({
  id,
  kind,
  name,
  language: "en",
  status: "ready",
  hasPreview: true,
  labels: {},
  tags: [],
  createdAt: "2026-10-01T10:00:00Z",
  updatedAt: "2026-10-01T10:00:00Z",
});

let randomUuid: MockInstance<Crypto["randomUUID"]>;

beforeEach(() => {
  vi.clearAllMocks();
  api.listStyles.mockResolvedValue({ items: styles });
  api.estimateJob.mockResolvedValue(estimateView());
  api.createJob.mockResolvedValue(job());
  topicApi.resolveTopicReference.mockResolvedValue(null);
  usersApi.userPreferences.mockResolvedValue({
    captionsEnabled: true,
    defaultAspect: "16:9",
    defaultStyle: "minimal-dark",
    defaultVoiceId: null,
    depth: "standard",
    language: "en",
    pace: "normal",
  });
  platformApi.publicSettings.mockResolvedValue({
    settings: {
      "preferences.languages": ["en", "hi"],
      "preferences.aspects": ["16:9", "9:16", "1:1"],
    },
  });
  platformApi.evaluatedFlags.mockResolvedValue({ flags: {} });
  creditsApi.getWallet.mockResolvedValue({
    available: 500,
    balance: 500,
    reserved: 0,
    expiringSoon: [],
  });
  voicesApi.listVoices.mockResolvedValue({
    items: [voice(VOICE_ID, "builtin", "Aria"), voice(CLONED_VOICE_ID, "cloned", "My voice")],
    nextCursor: null,
  });
  catalogApi.searchCatalog.mockResolvedValue({ items: [], nextCursor: null });
  randomUuid = vi.spyOn(globalThis.crypto, "randomUUID");
  randomUuid.mockReset();
  randomUuid
    .mockReturnValueOnce(KEY_ONE)
    .mockReturnValueOnce(KEY_TWO)
    .mockReturnValueOnce(KEY_THREE);
});

const openForm = async (props: { topicReference?: string | null; initialQuery?: string } = {}) => {
  const view = renderWithQuery(
    <CreateVideoForm
      topicReference={props.topicReference ?? null}
      initialQuery={props.initialQuery ?? ""}
    />,
  );
  await screen.findByRole("form", { name: "Create a video" });
  return view;
};

const question = () => screen.getByRole("textbox", { name: "What should the video explain?" });

describe("CreateVideoForm", () => {
  it("shows the options with the saved preferences as defaults", async () => {
    await openForm();
    expect(screen.getByRole("slider", { name: "Video length in seconds" })).toHaveAttribute(
      "aria-valuenow",
      "60",
    );
    expect(screen.getByRole("button", { name: "16:9 landscape" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "9:16 portrait" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(screen.getByRole("radio", { name: /Minimal dark/ })).toBeChecked();
    expect(
      screen.getByRole("switch", { name: "Review storyboard before rendering" }),
    ).not.toBeChecked();
    expect(screen.getByRole("combobox", { name: "Language" })).toHaveValue("en");
    expect(screen.getAllByTestId("style-swatch")).toHaveLength(2);
  });

  it("renders the style swatch from the API palette through inline custom properties", async () => {
    await openForm();
    const swatch = screen.getAllByTestId("style-swatch")[0];
    expect(swatch?.style.getPropertyValue("--swatch-background")).toBe(styles[0]?.background);
    expect(swatch?.style.getPropertyValue("--swatch-accent")).toBe(styles[0]?.accent);
  });

  it("lists built-in and cloned voices and marks the premium", async () => {
    const user = userEvent.setup();
    await openForm();
    const select = await screen.findByRole("combobox", { name: "Narration voice" });
    await waitFor(() => {
      expect(within(select).getByRole("option", { name: /My voice/ })).toBeInTheDocument();
    });
    await user.selectOptions(select, CLONED_VOICE_ID);
    expect(screen.getByText(/premium and add 10 credits/)).toBeInTheDocument();
  });

  it("validates the question inline and does not submit", async () => {
    const user = userEvent.setup();
    await openForm();
    await user.click(screen.getByRole("button", { name: "Create video" }));
    expect(
      await screen.findByText("Describe what the video should explain, or pick a topic."),
    ).toBeInTheDocument();
    expect(api.createJob).not.toHaveBeenCalled();
  });

  it("keeps at least one aspect ratio selected", async () => {
    const user = userEvent.setup();
    await openForm();
    await user.click(screen.getByRole("button", { name: "16:9 landscape" }));
    expect(screen.getByRole("button", { name: "16:9 landscape" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await user.click(screen.getByRole("button", { name: "9:16 portrait" }));
    await user.click(screen.getByRole("button", { name: "16:9 landscape" }));
    expect(screen.getByRole("button", { name: "9:16 portrait" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "16:9 landscape" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("allows burn-in only while subtitles are on", async () => {
    const user = userEvent.setup();
    await openForm();
    const burnIn = screen.getByRole("switch", { name: "Burn subtitles into the video" });
    const subtitles = screen.getByRole("switch", { name: "Subtitles" });
    expect(burnIn).toBeEnabled();
    await user.click(burnIn);
    expect(burnIn).toBeChecked();
    await user.click(subtitles);
    expect(burnIn).toBeDisabled();
    expect(burnIn).not.toBeChecked();
    await user.click(subtitles);
    expect(burnIn).toBeEnabled();
  });

  it("estimates after a pause and shows the cost beside the balance", async () => {
    const user = userEvent.setup();
    await openForm();
    await waitFor(() => {
      expect(api.estimateJob).toHaveBeenCalledWith({
        durationSeconds: 60,
        aspects: ["16:9"],
        voiceId: null,
      });
    });
    expect(await screen.findByText("140 credits")).toBeInTheDocument();
    expect(await screen.findByText("500 credits")).toBeInTheDocument();
    expect(screen.getByText("Your balance covers this video.")).toBeInTheDocument();

    api.estimateJob.mockClear();
    const slider = screen.getByRole("slider", { name: "Video length in seconds" });
    slider.focus();
    await user.keyboard("{ArrowRight}{ArrowRight}");
    expect(slider).toHaveAttribute("aria-valuenow", "70");
    expect(api.estimateJob).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(api.estimateJob).toHaveBeenCalledTimes(1);
    });
    expect(api.estimateJob).toHaveBeenCalledWith({
      durationSeconds: 70,
      aspects: ["16:9"],
      voiceId: null,
    });
  });

  it("replaces the submit button with a buy credits link when the balance is short", async () => {
    api.estimateJob.mockResolvedValue(
      estimateView({ affordable: false, availableCredits: 20, credits: 140 }),
    );
    await openForm();
    const buy = await screen.findByRole("link", { name: "Buy credits to continue" });
    expect(buy).toHaveAttribute("href", "/billing/credits");
    expect(screen.queryByRole("button", { name: "Create video" })).not.toBeInTheDocument();
    expect(await screen.findByText(/You need 120 more credits/)).toBeInTheDocument();
  });

  it("submits the request and opens the job page", async () => {
    const user = userEvent.setup();
    await openForm();
    await user.type(question(), "How does a hash map work?");
    await user.click(screen.getByRole("button", { name: "Create video" }));
    await waitFor(() => {
      expect(router.push).toHaveBeenCalledWith(`/jobs/${JOB_ID}`);
    });
    expect(api.createJob.mock.calls[0]?.[0]).toEqual({
      idempotencyKey: KEY_ONE,
      request: {
        query: "How does a hash map work?",
        topicId: null,
        options: {
          durationSeconds: 60,
          aspects: ["16:9"],
          style: "minimal-dark",
          language: "en",
          voiceId: null,
          reviewStoryboard: false,
          subtitles: true,
          burnInSubtitles: false,
        },
      },
    });
  });

  it("reuses the key for a retry of the same click and uses a fresh key for the next one", async () => {
    const user = userEvent.setup();
    api.createJob
      .mockRejectedValueOnce(ApiError.ofKind("network"))
      .mockResolvedValueOnce(job())
      .mockResolvedValueOnce(job());
    await openForm();
    await user.type(question(), "How does a hash map work?");
    const submit = screen.getByRole("button", { name: "Create video" });
    await user.click(submit);
    expect(await screen.findByText(/Something went wrong/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Create video" }));
    await waitFor(() => {
      expect(router.push).toHaveBeenCalledTimes(1);
    });
    await user.click(screen.getByRole("button", { name: "Create video" }));
    await waitFor(() => {
      expect(api.createJob).toHaveBeenCalledTimes(3);
    });
    const keys = api.createJob.mock.calls.map(
      (call) => (call[0] as { idempotencyKey: string }).idempotencyKey,
    );
    expect(keys).toEqual([KEY_ONE, KEY_ONE, KEY_TWO]);
  });

  it("uses a new key after a failure that cannot be retried", async () => {
    const user = userEvent.setup();
    api.createJob
      .mockRejectedValueOnce(
        new ApiError({
          kind: "http",
          status: 422,
          code: "style_not_found",
          title: "Style",
          detail: null,
        }),
      )
      .mockResolvedValueOnce(job());
    await openForm();
    await user.type(question(), "How does a hash map work?");
    await user.click(screen.getByRole("button", { name: "Create video" }));
    expect(await screen.findByText(/style is no longer available/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Create video" }));
    await waitFor(() => {
      expect(api.createJob).toHaveBeenCalledTimes(2);
    });
    const keys = api.createJob.mock.calls.map(
      (call) => (call[0] as { idempotencyKey: string }).idempotencyKey,
    );
    expect(keys).toEqual([KEY_ONE, KEY_TWO]);
  });

  it.each([
    ["too_many_active_jobs", 409, /videos in progress/],
    ["insufficient_credits", 402, /enough credits/],
    ["topic_not_found", 404, /topic is no longer available/],
    ["rate_limited", 429, /Please wait/],
  ])("explains the %s problem", async (code, status, message) => {
    const user = userEvent.setup();
    api.createJob.mockRejectedValueOnce(
      new ApiError({ kind: "http", status, code, title: "Problem", detail: null }),
    );
    await openForm();
    await user.type(question(), "How does a hash map work?");
    await user.click(screen.getByRole("button", { name: "Create video" }));
    expect(await screen.findByText(message)).toBeInTheDocument();
  });

  it("shows the policy message of a refused request", async () => {
    const user = userEvent.setup();
    api.createJob.mockRejectedValueOnce(
      new ApiError({
        kind: "http",
        status: 422,
        code: "input_refused",
        title: "Request not supported",
        detail: "Motionile does not make sexually explicit videos.",
      }),
    );
    await openForm();
    await user.type(question(), "something refused");
    await user.click(screen.getByRole("button", { name: "Create video" }));
    expect(
      await screen.findByText("Motionile does not make sexually explicit videos."),
    ).toBeInTheDocument();
  });

  it("preselects a topic from the link and sends only the topic", async () => {
    const user = userEvent.setup();
    topicApi.resolveTopicReference.mockResolvedValue({
      id: TOPIC_ID,
      title: "Hash maps",
      suggestedDurationSeconds: 90,
    });
    await openForm({ topicReference: "hash-maps" });
    expect(screen.getByText("Hash maps")).toBeInTheDocument();
    expect(screen.getByRole("slider", { name: "Video length in seconds" })).toHaveAttribute(
      "aria-valuenow",
      "90",
    );
    await user.click(screen.getByRole("button", { name: "Create video" }));
    await waitFor(() => {
      expect(api.createJob).toHaveBeenCalled();
    });
    expect(api.createJob.mock.calls[0]?.[0]).toMatchObject({
      request: { topicId: TOPIC_ID, query: null },
    });
  });

  it("tells the user when the linked topic does not exist", async () => {
    await openForm({ topicReference: "missing-topic" });
    expect(await screen.findByText(/That topic could not be found/)).toBeInTheDocument();
    expect(question()).toBeInTheDocument();
  });

  it("suggests catalog topics while typing and lets the user clear the choice", async () => {
    const user = userEvent.setup();
    catalogApi.searchCatalog.mockResolvedValue({
      items: [
        {
          id: TOPIC_ID,
          title: "Hash maps",
          slug: "hash-maps",
          summary: "Key value storage.",
          suggestedDurationMs: 45_000,
          path: "/explore/a/b/hash-maps",
        },
      ],
      nextCursor: null,
    });
    await openForm();
    await user.type(question(), "hash");
    const suggestion = await screen.findByRole("button", { name: /Hash maps/ });
    await user.click(suggestion);
    expect(screen.getByRole("slider", { name: "Video length in seconds" })).toHaveAttribute(
      "aria-valuenow",
      "45",
    );
    await user.click(screen.getByRole("button", { name: "Clear topic" }));
    expect(question()).toBeInTheDocument();
  });

  it("prefills the question from a retry link", async () => {
    await openForm({ initialQuery: "How does DNS work?" });
    expect(question()).toHaveValue("How does DNS work?");
  });
});

describe("useJobEstimate", () => {
  it("waits for the input to settle before asking the server", async () => {
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={makeTestQueryClient()}>{children}</QueryClientProvider>
    );
    const { result, rerender } = renderHook(
      ({ seconds }: { seconds: number }) =>
        useJobEstimate({ durationSeconds: seconds, aspects: ["16:9"], voiceId: null }),
      { wrapper, initialProps: { seconds: 30 } },
    );
    await waitFor(() => {
      expect(result.current.estimate?.credits).toBe(140);
    });
    api.estimateJob.mockClear();
    api.estimateJob.mockResolvedValue(estimateView({ credits: 200, seconds: 45 }));
    rerender({ seconds: 40 });
    rerender({ seconds: 45 });
    expect(result.current.isSettling).toBe(true);
    expect(result.current.estimate?.credits).toBe(140);
    await waitFor(() => {
      expect(result.current.estimate?.credits).toBe(200);
    });
    expect(api.estimateJob).toHaveBeenCalledTimes(1);
    expect(api.estimateJob).toHaveBeenCalledWith({
      durationSeconds: 45,
      aspects: ["16:9"],
      voiceId: null,
    });
  });
});
