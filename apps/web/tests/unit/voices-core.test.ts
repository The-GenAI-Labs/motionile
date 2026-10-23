import { beforeEach, describe, expect, it } from "vitest";

import {
  addTag,
  editValuesFor,
  hasVoiceChanges,
  toVoiceUpdate,
  voiceEditSchema,
} from "@/features/admin-voices/schemas/admin-voices.schema";
import {
  isRetryableCloneError,
  voiceErrorGuidance,
  voiceErrorMessage,
  voiceFailureGuidance,
  voiceFailureMessage,
} from "@/features/voices/errors";
import {
  extensionFor,
  isRecordingSupported,
  rmsLevel,
} from "@/features/voices/hooks/use-audio-recorder";
import { voiceKeys } from "@/features/voices/query-keys";
import {
  cloneSubmitFormSchema,
  isAudioBlob,
  languageLabel,
} from "@/features/voices/schemas/voices.schema";
import { useCloneWizardStore, wizardSteps } from "@/features/voices/store/clone-wizard.store";
import { ApiError } from "@/lib/api/api-error";
import { formatClockMs } from "@/lib/utils/format";

import { adminVoice, cloneStart } from "./voices-fixtures";

const problem = (code: string, status: number) =>
  new ApiError({ kind: "http", status, code, title: code, detail: null });

describe("voice error guidance", () => {
  it("explains every clone failure code", () => {
    for (const code of [
      "consent_mismatch",
      "sample_invalid",
      "provider_failed",
      "attempt_expired",
      "clone_stalled",
      "credit_reservation_expired",
      "preview_failed",
      "transcription_failed",
    ]) {
      expect(voiceFailureGuidance[code]).toBeTruthy();
    }
    expect(voiceFailureMessage("consent_mismatch")).toContain("consent sentence");
    expect(voiceFailureMessage("credit_reservation_expired")).toContain("No credits were taken");
    expect(voiceFailureMessage("unknown")).toContain("could not be created");
    expect(voiceFailureMessage(null)).toContain("could not be created");
  });

  it("explains every audio validation code", () => {
    for (const code of [
      "audio_not_audio",
      "audio_too_large",
      "audio_too_short",
      "audio_too_long",
      "audio_video_stream_present",
      "audio_unsupported_format",
      "audio_probe_failed",
    ]) {
      expect(voiceErrorGuidance[code]).toBeTruthy();
      expect(voiceErrorMessage(problem(code, 422))).toBe(voiceErrorGuidance[code]);
    }
  });

  it("maps a payload too large status and the busy conflict", () => {
    expect(voiceErrorMessage(problem("anything", 413))).toBe(voiceErrorGuidance["audio_too_large"]);
    expect(voiceErrorMessage(problem("voice_busy", 409))).toContain("still being created");
  });

  it("retries only transient errors and the in-progress idempotency conflict", () => {
    expect(isRetryableCloneError(ApiError.ofKind("network"))).toBe(true);
    expect(isRetryableCloneError(problem("idempotency_request_in_progress", 409))).toBe(true);
    expect(isRetryableCloneError(problem("voice_quota_exceeded", 409))).toBe(false);
  });
});

describe("voice schemas", () => {
  it("validates the voice name and language", () => {
    expect(cloneSubmitFormSchema.safeParse({ name: "My voice", language: "en" }).success).toBe(
      true,
    );
    expect(cloneSubmitFormSchema.safeParse({ name: "  ", language: "en" }).success).toBe(false);
    expect(cloneSubmitFormSchema.safeParse({ name: "x".repeat(81), language: "en" }).success).toBe(
      false,
    );
    expect(cloneSubmitFormSchema.safeParse({ name: "Ok", language: "English!" }).success).toBe(
      false,
    );
    expect(cloneSubmitFormSchema.safeParse({ name: "Ok", language: "pt-BR" }).success).toBe(true);
  });

  it("accepts audio blobs and recordings without a type", () => {
    expect(isAudioBlob(new Blob([], { type: "audio/webm" }))).toBe(true);
    expect(isAudioBlob(new Blob([], { type: "video/webm" }))).toBe(true);
    expect(isAudioBlob(new Blob([], { type: "" }))).toBe(true);
    expect(isAudioBlob(new Blob([], { type: "image/png" }))).toBe(false);
  });

  it("labels languages and builds query keys from the feature keys", () => {
    expect(languageLabel("hi")).toBe("Hindi");
    expect(languageLabel("fr")).toBe("fr");
    expect(voiceKeys.list({ language: "en" })).toEqual(["voices", "list", { language: "en" }]);
    expect(voiceKeys.preview("v1")).toEqual(["voices", "preview", "v1"]);
  });

  it("formats clock times", () => {
    expect(formatClockMs(0)).toBe("00:00");
    expect(formatClockMs(65_900)).toBe("01:05");
  });
});

describe("recording helpers", () => {
  it("measures the input level between 0 and 100", () => {
    expect(rmsLevel(new Uint8Array(0))).toBe(0);
    expect(rmsLevel(new Uint8Array(64).fill(128))).toBe(0);
    expect(rmsLevel(new Uint8Array(64).fill(160))).toBe(100);
    const quiet = rmsLevel(new Uint8Array(64).fill(134));
    expect(quiet).toBeGreaterThan(0);
    expect(quiet).toBeLessThan(100);
  });

  it("picks an extension from the mime type and detects missing support", () => {
    expect(extensionFor("audio/webm;codecs=opus")).toBe("webm");
    expect(extensionFor("audio/mp4")).toBe("m4a");
    expect(extensionFor("audio/ogg")).toBe("ogg");
    expect(extensionFor("audio/x-unknown")).toBe("webm");
    expect(isRecordingSupported()).toBe(false);
  });
});

describe("clone wizard store", () => {
  beforeEach(() => {
    useCloneWizardStore.getState().reset();
  });

  it("starts at consent and moves to the recording step when an attempt starts", () => {
    expect(useCloneWizardStore.getState().step).toBe("consent");
    useCloneWizardStore.getState().setStart(cloneStart);

    expect(useCloneWizardStore.getState()).toMatchObject({
      step: "recording",
      start: cloneStart,
      consentUploaded: false,
    });
  });

  it("tracks uploads and clears them on reset", () => {
    const store = useCloneWizardStore.getState();
    store.addUpload({ id: "u1", name: "a.mp3", status: "uploading", message: null });
    store.updateUpload("u1", { status: "failed", message: "Too short" });

    expect(useCloneWizardStore.getState().uploads).toEqual([
      { id: "u1", name: "a.mp3", status: "failed", message: "Too short" },
    ]);
    useCloneWizardStore.getState().removeUpload("u1");
    expect(useCloneWizardStore.getState().uploads).toEqual([]);
    useCloneWizardStore.getState().setSubmittedVoiceId("v1");
    expect(useCloneWizardStore.getState().step).toBe("status");
    useCloneWizardStore.getState().reset();
    expect(useCloneWizardStore.getState()).toMatchObject({
      step: "consent",
      submittedVoiceId: null,
    });
    expect(wizardSteps).toHaveLength(5);
  });

  it("drops the consent upload flag when the clip changes", () => {
    const store = useCloneWizardStore.getState();
    store.setConsentUploaded(true);
    store.setConsentClip(null);

    expect(useCloneWizardStore.getState().consentUploaded).toBe(false);
  });
});

describe("admin voice editing", () => {
  const voice = adminVoice({ status: "disabled", tags: ["warm"] });

  it("sends only the changed fields", () => {
    const values = { ...editValuesFor(voice), name: "Aria Two", exposed: true };

    expect(toVoiceUpdate(values, voice)).toEqual({ name: "Aria Two", status: "ready" });
    expect(hasVoiceChanges(toVoiceUpdate(editValuesFor(voice), voice))).toBe(false);
    expect(toVoiceUpdate({ ...editValuesFor(voice), tags: ["warm", "calm"] }, voice)).toEqual({
      tags: ["warm", "calm"],
    });
    expect(toVoiceUpdate({ ...editValuesFor(adminVoice()), exposed: false }, adminVoice())).toEqual(
      { status: "disabled" },
    );
  });

  it("validates tags like the server does", () => {
    expect(addTag(["a"], "  Warm  ")).toEqual({ tags: ["a", "warm"], error: null });
    expect(addTag(["a"], "  ")).toEqual({ tags: ["a"], error: null });
    expect(addTag(["a"], "a").error).toContain("already added");
    expect(addTag(["a"], "-bad").error).toContain("lowercase");
    expect(
      addTag(
        Array.from({ length: 10 }, (_, index) => `t${String(index)}`),
        "x",
      ).error,
    ).toContain("at most 10");
    expect(voiceEditSchema.safeParse({ ...editValuesFor(voice), language: "EN us" }).success).toBe(
      false,
    );
  });
});
