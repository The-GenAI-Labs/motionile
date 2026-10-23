import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CloneWizard } from "@/features/voices/components/clone-wizard";
import { useCloneWizardStore } from "@/features/voices/store/clone-wizard.store";
import { ApiError } from "@/lib/api/api-error";

import { installFakeRecording, removeRecordingSupport } from "./media-fakes";
import { renderWithQuery } from "./render-with-query";
import { attempt, ATTEMPT_ID, CLONED_ID, cloneStart, SAMPLE_ID, voice } from "./voices-fixtures";

const voicesApi = vi.hoisted(() => ({
  startClone: vi.fn(),
  getCloneAttempt: vi.fn(),
  uploadConsentRecording: vi.fn(),
  addCloneSample: vi.fn(),
  removeCloneSample: vi.fn(),
  submitClone: vi.fn(),
  getVoice: vi.fn(),
}));
const platformApi = vi.hoisted(() => ({ publicSettings: vi.fn() }));

vi.mock("@/features/voices/api/voices.api", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  ...voicesApi,
}));
vi.mock("@/features/platform/api/platform.api", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  ...platformApi,
}));

const problem = (code: string, status: number) =>
  new ApiError({ kind: "http", status, code, title: code, detail: null });

const sample = (id: string, durationMs: number) => ({ id, durationMs, sizeBytes: 1000 });

const goTo = (step: "samples" | "details" | "status", extra: object = {}) => {
  useCloneWizardStore.setState({
    step,
    start: cloneStart,
    consentUploaded: true,
    ...extra,
  });
};

const recordFor = async (
  user: ReturnType<typeof userEvent.setup>,
  milliseconds: number,
  start = "Start recording",
) => {
  await user.click(screen.getByRole("button", { name: start }));
  await screen.findByRole("button", { name: "Stop recording" });
  act(() => {
    vi.advanceTimersByTime(milliseconds);
  });
  await user.click(screen.getByRole("button", { name: "Stop recording" }));
};

let recording: ReturnType<typeof installFakeRecording>;

beforeEach(() => {
  vi.clearAllMocks();
  useCloneWizardStore.getState().reset();
  platformApi.publicSettings.mockResolvedValue({
    settings: {
      "voices.consent_statement": cloneStart.statementText,
      "voices.consent_statement_version": cloneStart.statementVersion,
    },
  });
  voicesApi.startClone.mockResolvedValue(cloneStart);
  voicesApi.getCloneAttempt.mockResolvedValue(attempt());
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "performance"] });
  recording = installFakeRecording();
});

afterEach(() => {
  recording.restore();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

const newUser = () => userEvent.setup({ delay: null });

describe("consent step", () => {
  it("shows the statement and its version and requires acceptance", async () => {
    const user = newUser();
    renderWithQuery(<CloneWizard />);

    expect(await screen.findByText(cloneStart.statementText)).toBeInTheDocument();
    expect(screen.getByText("Version 2026-10-19")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Step 1 of 5: Consent" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Accept and continue" }));

    expect(await screen.findByText("Accept the statement to continue.")).toBeInTheDocument();
    expect(voicesApi.startClone).not.toHaveBeenCalled();
  });

  it("starts the attempt with the shown version and moves focus to the next step", async () => {
    const user = newUser();
    renderWithQuery(<CloneWizard />);

    await user.click(
      await screen.findByRole("checkbox", {
        name: "I have read and accept this statement. The voice I clone is my own.",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Accept and continue" }));

    const heading = await screen.findByRole("heading", {
      level: 2,
      name: "Step 2 of 5: Consent recording",
    });
    expect(voicesApi.startClone.mock.calls[0]?.[0]).toBe("2026-10-19");
    expect(heading).toHaveFocus();
    expect(screen.getByText(cloneStart.consentSentence)).toBeInTheDocument();
    const steps = within(screen.getByRole("list", { name: "Cloning steps" })).getAllByRole(
      "listitem",
    );
    expect(steps[1]).toHaveAttribute("aria-current", "step");
    expect(steps[0]).toHaveTextContent("(done)");
  });

  it("asks the user to review an outdated statement", async () => {
    voicesApi.startClone.mockRejectedValue(problem("consent_statement_outdated", 409));
    const user = newUser();
    renderWithQuery(<CloneWizard />);

    const checkbox = await screen.findByRole("checkbox", { name: /I have read and accept/ });
    await user.click(checkbox);
    await user.click(screen.getByRole("button", { name: "Accept and continue" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("statement changed");
    await waitFor(() => {
      expect(platformApi.publicSettings).toHaveBeenCalledTimes(2);
    });
    expect(screen.getByRole("checkbox", { name: /I have read and accept/ })).not.toBeChecked();
  });

  it("offers a retry when the statement cannot be loaded", async () => {
    platformApi.publicSettings.mockResolvedValueOnce({ settings: {} });
    const user = newUser();
    renderWithQuery(<CloneWizard />);

    expect(await screen.findByRole("alert")).toHaveTextContent("could not be loaded");
    await user.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByText(cloneStart.statementText)).toBeInTheDocument();
  });
});

describe("consent recording step", () => {
  const startAt = (step: "recording" = "recording") => {
    useCloneWizardStore.setState({ step, start: cloneStart });
  };

  it("records, plays back, uploads and unlocks the next step", async () => {
    voicesApi.uploadConsentRecording.mockResolvedValue(
      attempt({ consentRecording: { durationMs: 5000, sizeBytes: 1000 } }),
    );
    const user = newUser();
    startAt();
    renderWithQuery(<CloneWizard />);

    expect(screen.getByRole("button", { name: "Continue to voice samples" })).toBeDisabled();
    await recordFor(user, 5000);

    expect(screen.getByRole("timer", { name: "Recording length" })).toHaveTextContent("00:05");
    expect(screen.getByText("Recording stopped. It is 00:05 long.")).toBeInTheDocument();
    const playback = screen.getByLabelText("Playback of your consent sentence recording");
    expect(playback).toHaveAttribute("src", "blob:fake-recording");
    expect(screen.getByRole("button", { name: "Record again" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Upload this recording" }));

    expect(await screen.findByText("Consent recording uploaded (00:05).")).toBeInTheDocument();
    const upload = voicesApi.uploadConsentRecording.mock.calls[0]?.[0] as {
      attemptId: string;
      file: Blob;
      filename: string;
    };
    expect(upload.attemptId).toBe(ATTEMPT_ID);
    expect(upload.filename).toBe("recording.webm");
    expect(upload.file).toBeInstanceOf(Blob);
    await user.click(screen.getByRole("button", { name: "Continue to voice samples" }));

    expect(
      await screen.findByRole("heading", { level: 2, name: "Step 3 of 5: Voice samples" }),
    ).toBeInTheDocument();
  });

  it("shows a live input level meter and the length counter while recording", async () => {
    const user = newUser();
    startAt();
    renderWithQuery(<CloneWizard />);

    await user.click(screen.getByRole("button", { name: "Start recording" }));
    await screen.findByRole("button", { name: "Stop recording" });
    act(() => {
      vi.advanceTimersByTime(1200);
    });

    const meter = screen.getByRole("meter", { name: "Microphone level" });
    expect(meter).toHaveAttribute("aria-valuenow", "100");
    expect(meter).toHaveAttribute("aria-valuetext", "100 percent");
    expect(screen.getByRole("timer", { name: "Recording length" })).toHaveTextContent("00:01");
    expect(screen.getByText("Recording started.")).toBeInTheDocument();
    expect(recording.getUserMedia).toHaveBeenCalledWith({ audio: true });
  });

  it("stops at the maximum length by itself", async () => {
    const user = newUser();
    startAt();
    renderWithQuery(<CloneWizard />);

    await user.click(screen.getByRole("button", { name: "Start recording" }));
    await screen.findByRole("button", { name: "Stop recording" });
    act(() => {
      vi.advanceTimersByTime(31_000);
    });

    expect(await screen.findByRole("button", { name: "Record again" })).toBeInTheDocument();
    expect(screen.getByRole("timer", { name: "Recording length" })).toHaveTextContent("00:30");
  });

  it("refuses a recording that is too short", async () => {
    const user = newUser();
    startAt();
    renderWithQuery(<CloneWizard />);

    await recordFor(user, 1000);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "too short. Record at least 3 seconds",
    );
    expect(screen.queryByRole("button", { name: "Upload this recording" })).not.toBeInTheDocument();
  });

  it("lets the user record again and replaces the clip", async () => {
    const user = newUser();
    startAt();
    renderWithQuery(<CloneWizard />);

    await recordFor(user, 4000);
    await recordFor(user, 6000, "Record again");

    expect(screen.getByRole("timer", { name: "Recording length" })).toHaveTextContent("00:06");
    expect(screen.getAllByLabelText("Playback of your consent sentence recording")).toHaveLength(1);
  });

  it("explains the server problem when the upload fails", async () => {
    voicesApi.uploadConsentRecording.mockRejectedValue(problem("audio_too_short", 422));
    const user = newUser();
    startAt();
    renderWithQuery(<CloneWizard />);

    await recordFor(user, 5000);
    await user.click(screen.getByRole("button", { name: "Upload this recording" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("This recording is too short.");
    expect(screen.getByRole("button", { name: "Continue to voice samples" })).toBeDisabled();
  });

  it("shows the microphone-denied state with an upload fallback", async () => {
    recording.restore();
    recording = installFakeRecording({ denied: true });
    voicesApi.uploadConsentRecording.mockResolvedValue(
      attempt({ consentRecording: { durationMs: 7000, sizeBytes: 1000 } }),
    );
    const user = newUser();
    startAt();
    renderWithQuery(<CloneWizard />);

    await user.click(screen.getByRole("button", { name: "Start recording" }));

    expect(await screen.findByText("Microphone access was blocked.")).toBeInTheDocument();
    const input = screen.getByLabelText("Upload an audio file for the consent sentence");
    expect(input).toHaveAttribute("accept", "audio/*");
    await user.upload(input, new File(["x"], "me.wav", { type: "audio/wav" }));

    expect(await screen.findByText("Consent recording uploaded (00:07).")).toBeInTheDocument();
    expect(
      (voicesApi.uploadConsentRecording.mock.calls[0]?.[0] as { filename: string }).filename,
    ).toBe("me.wav");
  });

  it("shows the unsupported-browser state with an upload fallback and no record button", () => {
    recording.restore();
    const restore = removeRecordingSupport();
    startAt();
    renderWithQuery(<CloneWizard />);

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Recording is not supported in this browser.",
    );
    expect(screen.queryByRole("button", { name: "Start recording" })).not.toBeInTheDocument();
    expect(
      screen.getByLabelText("Upload an audio file for the consent sentence"),
    ).toBeInTheDocument();
    restore();
    recording = installFakeRecording();
  });

  it("stops the microphone when the page is left while recording", async () => {
    const user = newUser();
    startAt();
    const { unmount } = renderWithQuery(<CloneWizard />);

    await user.click(screen.getByRole("button", { name: "Start recording" }));
    await screen.findByRole("button", { name: "Stop recording" });
    unmount();

    expect(recording.stopTrack).toHaveBeenCalled();
    expect(recording.contextClosed).toHaveBeenCalled();
    expect(useCloneWizardStore.getState().step).toBe("consent");
  });

  it("stops the microphone tracks after a normal stop", async () => {
    const user = newUser();
    startAt();
    renderWithQuery(<CloneWizard />);

    await recordFor(user, 4000);

    expect(recording.stopTrack).toHaveBeenCalledTimes(1);
  });
});

describe("samples step", () => {
  it("shows the collected length against the minimum and keeps continue locked", async () => {
    voicesApi.getCloneAttempt.mockResolvedValue(
      attempt({ samples: [sample(SAMPLE_ID, 20_000)], totalSampleMs: 20_000 }),
    );
    goTo("samples");
    renderWithQuery(<CloneWizard />);

    const bar = await screen.findByRole("progressbar", { name: "Sample length collected" });
    expect(bar).toHaveAttribute("aria-valuenow", "67");
    expect(bar).toHaveAttribute("aria-valuetext", "00:20 collected of at least 00:30");
    expect(screen.getByText("00:20 of 00:30 minimum, 05:00 maximum")).toBeInTheDocument();
    const list = screen.getByRole("list", { name: "Added samples" });
    expect(within(list).getByText("Sample 1")).toBeInTheDocument();
    expect(within(list).getByText("00:20")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue to name and language" })).toBeDisabled();
  });

  it("uploads several files in order and unlocks continue at the minimum", async () => {
    voicesApi.getCloneAttempt.mockResolvedValue(attempt());
    voicesApi.addCloneSample
      .mockResolvedValueOnce(attempt({ samples: [sample("s1", 20_000)], totalSampleMs: 20_000 }))
      .mockResolvedValueOnce(
        attempt({ samples: [sample("s1", 20_000), sample("s2", 15_000)], totalSampleMs: 35_000 }),
      );
    const user = newUser();
    goTo("samples");
    renderWithQuery(<CloneWizard />);

    await user.upload(await screen.findByLabelText("Upload voice sample files"), [
      new File(["a"], "one.mp3", { type: "audio/mpeg" }),
      new File(["b"], "two.mp3", { type: "audio/mpeg" }),
    ]);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Continue to name and language" })).toBeEnabled();
    });
    expect(
      voicesApi.addCloneSample.mock.calls.map((call) => (call[0] as { filename: string }).filename),
    ).toEqual(["one.mp3", "two.mp3"]);
    const list = screen.getByRole("list", { name: "Added samples" });
    expect(within(list).getByText("Sample 2")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Sample length collected" })).toHaveAttribute(
      "aria-valuenow",
      "100",
    );
    expect(screen.getByText("two.mp3 was added.")).toBeInTheDocument();
  });

  it("shows the server error for a rejected file and lets the user dismiss it", async () => {
    voicesApi.addCloneSample.mockRejectedValue(problem("audio_video_stream_present", 422));
    const user = newUser();
    goTo("samples");
    renderWithQuery(<CloneWizard />);

    await user.upload(
      await screen.findByLabelText("Upload voice sample files"),
      new File(["a"], "clip.mp4", { type: "audio/mp4" }),
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("contains video");
    expect(screen.getByText("clip.mp4")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Dismiss the error for clip.mp4" }));
    expect(screen.queryByText("clip.mp4")).not.toBeInTheDocument();
  });

  it.each([
    ["audio_not_audio", "not audio"],
    ["audio_too_large", "too large"],
    ["audio_too_short", "too short"],
    ["audio_too_long", "too long"],
    ["audio_unsupported_format", "not supported"],
    ["audio_probe_failed", "could not be read"],
  ])("explains %s", async (code, text) => {
    voicesApi.addCloneSample.mockRejectedValue(problem(code, 422));
    const user = newUser();
    goTo("samples");
    renderWithQuery(<CloneWizard />);

    await user.upload(
      await screen.findByLabelText("Upload voice sample files"),
      new File(["a"], "x.wav", { type: "audio/wav" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(text);
  });

  it("removes a sample", async () => {
    voicesApi.getCloneAttempt.mockResolvedValue(
      attempt({ samples: [sample(SAMPLE_ID, 40_000)], totalSampleMs: 40_000 }),
    );
    voicesApi.removeCloneSample.mockResolvedValue(attempt());
    const user = newUser();
    goTo("samples");
    renderWithQuery(<CloneWizard />);

    await user.click(await screen.findByRole("button", { name: "Remove sample 1" }));

    await waitFor(() => {
      expect(voicesApi.removeCloneSample).toHaveBeenCalledWith(ATTEMPT_ID, SAMPLE_ID);
    });
    expect(await screen.findByText("No samples added yet.")).toBeInTheDocument();
  });

  it("records a sample and adds it", async () => {
    voicesApi.addCloneSample.mockResolvedValue(
      attempt({ samples: [sample("s1", 40_000)], totalSampleMs: 40_000 }),
    );
    const user = newUser();
    goTo("samples");
    renderWithQuery(<CloneWizard />);

    await screen.findByRole("progressbar", { name: "Sample length collected" });
    await recordFor(user, 6000);
    await user.click(screen.getByRole("button", { name: "Add this recording as a sample" }));

    await waitFor(() => {
      expect(voicesApi.addCloneSample).toHaveBeenCalledTimes(1);
    });
    expect((voicesApi.addCloneSample.mock.calls[0]?.[0] as { filename: string }).filename).toBe(
      "recording.webm",
    );
    expect(await screen.findByText("recording.webm was added.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue to name and language" })).toBeEnabled();
  });

  it("blocks continue when the samples exceed the maximum", async () => {
    voicesApi.getCloneAttempt.mockResolvedValue(
      attempt({ samples: [sample("s1", 310_000)], totalSampleMs: 310_000 }),
    );
    goTo("samples");
    renderWithQuery(<CloneWizard />);

    expect(await screen.findByRole("alert")).toHaveTextContent("longer than 05:00");
    expect(screen.getByRole("button", { name: "Continue to name and language" })).toBeDisabled();
  });
});

describe("details and status steps", () => {
  it("validates the name and submits with an idempotency key", async () => {
    voicesApi.submitClone.mockResolvedValue(
      voice({ id: CLONED_ID, kind: "cloned", status: "pending", hasPreview: false }),
    );
    voicesApi.getVoice.mockResolvedValue(
      voice({ id: CLONED_ID, kind: "cloned", status: "pending", hasPreview: false }),
    );
    const user = newUser();
    goTo("details");
    renderWithQuery(<CloneWizard />);

    await user.click(screen.getByRole("button", { name: "Create my voice" }));
    expect(await screen.findByText("Enter a name for the voice.")).toBeInTheDocument();
    expect(voicesApi.submitClone).not.toHaveBeenCalled();
    await user.type(screen.getByRole("textbox", { name: "Voice name" }), "  My voice ");
    await user.selectOptions(screen.getByRole("combobox", { name: "Language you speak" }), "hi");
    await user.click(screen.getByRole("button", { name: "Create my voice" }));

    expect(
      await screen.findByRole("heading", { level: 2, name: "Step 5 of 5: Status" }),
    ).toBeInTheDocument();
    const [attemptId, input] = voicesApi.submitClone.mock.calls[0] as [
      string,
      { name: string; language: string; idempotencyKey: string },
    ];
    expect(attemptId).toBe(ATTEMPT_ID);
    expect(input).toMatchObject({ name: "My voice", language: "hi" });
    expect(input.idempotencyKey).toMatch(/^[0-9a-f-]{36}$/);
    expect(screen.getByRole("status")).toHaveTextContent("Creating your voice");
  });

  it("reuses the idempotency key when the same submission is retried after a network error", async () => {
    voicesApi.submitClone
      .mockRejectedValueOnce(ApiError.ofKind("network"))
      .mockResolvedValueOnce(voice({ id: CLONED_ID, kind: "cloned", status: "pending" }));
    voicesApi.getVoice.mockResolvedValue(
      voice({ id: CLONED_ID, kind: "cloned", status: "pending" }),
    );
    const user = newUser();
    goTo("details");
    renderWithQuery(<CloneWizard />);

    await user.type(screen.getByRole("textbox", { name: "Voice name" }), "My voice");
    await user.click(screen.getByRole("button", { name: "Create my voice" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong");
    await user.click(screen.getByRole("button", { name: "Create my voice" }));

    await screen.findByRole("heading", { level: 2, name: "Step 5 of 5: Status" });
    const keys = voicesApi.submitClone.mock.calls.map(
      (call) => (call[1] as { idempotencyKey: string }).idempotencyKey,
    );
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBe(keys[1]);
  });

  it("uses a new key after a rejection that cannot be retried", async () => {
    voicesApi.submitClone
      .mockRejectedValueOnce(problem("voice_quota_exceeded", 409))
      .mockRejectedValueOnce(problem("voice_quota_exceeded", 409));
    const user = newUser();
    goTo("details");
    renderWithQuery(<CloneWizard />);

    await user.type(screen.getByRole("textbox", { name: "Voice name" }), "My voice");
    await user.click(screen.getByRole("button", { name: "Create my voice" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("limit of cloned voices");
    await user.click(screen.getByRole("button", { name: "Create my voice" }));
    await waitFor(() => {
      expect(voicesApi.submitClone).toHaveBeenCalledTimes(2);
    });

    const keys = voicesApi.submitClone.mock.calls.map(
      (call) => (call[1] as { idempotencyKey: string }).idempotencyKey,
    );
    expect(keys[0]).not.toBe(keys[1]);
  });

  it("polls the voice until it is ready and links back to the gallery", async () => {
    voicesApi.getVoice
      .mockResolvedValueOnce(
        voice({ id: CLONED_ID, name: "My voice", kind: "cloned", status: "pending" }),
      )
      .mockResolvedValue(
        voice({ id: CLONED_ID, name: "My voice", kind: "cloned", status: "ready" }),
      );
    goTo("status", { submittedVoiceId: CLONED_ID });
    renderWithQuery(<CloneWizard />);

    expect(await screen.findByText(/Creating your voice/)).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4_100);
    });

    expect(await screen.findByText("My voice is ready to use.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to your voices" })).toHaveAttribute(
      "href",
      "/settings/voices",
    );
  });

  it("explains an expired credit reservation on the status screen", async () => {
    voicesApi.getVoice.mockResolvedValue(
      voice({
        id: CLONED_ID,
        kind: "cloned",
        status: "failed",
        failureCode: "credit_reservation_expired",
        hasPreview: false,
      }),
    );
    goTo("status", { submittedVoiceId: CLONED_ID });
    renderWithQuery(<CloneWizard />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "No credits were taken. Start again.",
    );
    expect(screen.getByRole("button", { name: "Start again" })).toBeInTheDocument();
  });

  it("shows the guidance for a failed clone and lets the user start again", async () => {
    voicesApi.getVoice.mockResolvedValue(
      voice({
        id: CLONED_ID,
        kind: "cloned",
        status: "failed",
        failureCode: "sample_invalid",
        hasPreview: false,
      }),
    );
    const user = newUser();
    goTo("status", { submittedVoiceId: CLONED_ID });
    renderWithQuery(<CloneWizard />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Your voice could not be created.");
    expect(alert).toHaveTextContent("provider could not use your samples");
    expect(screen.getByRole("link", { name: "Back to your voices" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Start again" }));

    expect(
      await screen.findByRole("heading", { level: 2, name: "Step 1 of 5: Consent" }),
    ).toBeInTheDocument();
  });
});
