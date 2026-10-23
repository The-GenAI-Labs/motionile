import { authErrorMessage } from "@/features/auth/errors";
import { ApiError } from "@/lib/api/api-error";

export const voiceErrorGuidance: Readonly<Record<string, string>> = {
  consent_statement_outdated:
    "The consent statement changed while you were reading it. Review the new text and accept it again.",
  voice_quota_exceeded: "You have reached the limit of cloned voices. Delete one to add another.",
  voice_not_found: "This voice no longer exists. Reload the list.",
  voice_preview_not_ready: "The preview for this voice is not ready yet.",
  voice_preview_failed: "The preview could not be generated. Try again shortly.",
  voice_not_available: "This voice is not available to select.",
  voice_busy: "This voice is still being created. You can delete it once it has finished.",
  voice_provider_unavailable:
    "The voice provider is unavailable, so the voice was kept. Try again shortly.",
  voice_update_empty: "Change at least one field before saving.",
  clone_attempt_not_found: "This cloning session expired. Start again.",
  clone_attempt_busy: "Another upload is in progress for this session. Wait a moment and retry.",
  clone_sample_not_found: "That sample no longer exists.",
  consent_recording_missing: "Record the consent sentence before continuing.",
  samples_too_short: "The samples are too short. Add more speech to reach the minimum.",
  samples_too_long: "The samples are too long. Remove a file to stay within the maximum.",
  too_many_samples: "You added too many files. Remove one before adding another.",
  audio_not_audio: "This file is not audio. Choose or record an audio file.",
  audio_too_large: "This file is too large. Choose a smaller file.",
  audio_too_short: "This recording is too short.",
  audio_too_long: "This recording is too long.",
  audio_video_stream_present: "This file contains video. Upload an audio-only file.",
  audio_unsupported_format: "This audio format is not supported. Try WAV, MP3, M4A or WebM.",
  audio_probe_failed: "This audio could not be read. The file may be corrupt.",
  insufficient_credits: "You do not have enough credits to clone a voice.",
  idempotency_request_in_progress:
    "Your previous attempt is still being processed. Try again in a moment.",
  idempotency_key_reused: "This request was already used. Submit the form again.",
  payload_too_large: "This file is too large. Choose a smaller file.",
  forbidden: "Your account is not allowed to do this.",
  validation_failed: "Check the highlighted fields and try again.",
};

export const voiceFailureGuidance: Readonly<Record<string, string>> = {
  consent_mismatch:
    "What you said did not match the consent sentence. Start again and read the sentence exactly as shown, in a quiet room.",
  sample_invalid:
    "The provider could not use your samples. Start again with clear, continuous speech and no background noise or music.",
  provider_failed:
    "The voice provider could not create the voice. Start again, or try later if it keeps happening.",
  preview_failed:
    "The voice was created but its preview failed. Start again, or contact support if it keeps happening.",
  transcription_failed:
    "Your consent recording could not be transcribed. Record it again in a quiet room.",
  attempt_expired: "The cloning session expired before it was submitted. Start again.",
  clone_stalled: "Creating the voice took too long and was stopped. Start again.",
  credit_reservation_expired:
    "The credits held for this voice expired before it finished, so the clone was refused. No credits were taken. Start again.",
};

export const voiceFailureMessage = (code: string | null | undefined): string =>
  (code ? voiceFailureGuidance[code] : undefined) ??
  "The voice could not be created. Start again, or contact support if it keeps happening.";

export const voiceErrorMessage = (error: unknown): string => {
  const normalized = ApiError.from(error);
  if (normalized.status === 413) {
    return voiceErrorGuidance["audio_too_large"] ?? authErrorMessage(error);
  }
  return voiceErrorGuidance[normalized.code] ?? authErrorMessage(error);
};

export const isRetryableCloneError = (error: unknown): boolean => {
  const normalized = ApiError.from(error);
  return normalized.isTransient || normalized.code === "idempotency_request_in_progress";
};
