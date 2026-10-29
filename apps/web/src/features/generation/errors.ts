import { authErrorMessage } from "@/features/auth/errors";
import { ApiError } from "@/lib/api/api-error";

export const generationErrorMessages: Readonly<Record<string, string>> = {
  insufficient_credits: "You do not have enough credits for this video.",
  too_many_active_jobs:
    "You already have the maximum number of videos in progress. Wait for one to finish or cancel it first.",
  topic_not_found: "That topic is no longer available. Pick another topic or describe your own.",
  style_not_found: "That style is no longer available. Choose another style.",
  language_not_supported: "That language is not available. Choose another language.",
  aspect_not_allowed: "One of the chosen aspect ratios is not available right now.",
  job_options_invalid: "Some of the options are not valid. Check them and try again.",
  voice_not_found: "That voice no longer exists. Choose another voice.",
  voice_not_available: "That voice is not ready yet. Choose another voice.",
  music_track_not_found: "That music track no longer exists.",
  music_track_unavailable: "That music track is not available right now.",
  job_not_found: "We could not find that video.",
  storyboard_not_found: "There is no storyboard for this video yet.",
  storyboard_not_editable: "The storyboard can only be changed while it waits for your review.",
  storyboard_version_conflict:
    "The storyboard changed since you opened it. Reload it to continue editing.",
  storyboard_invalid: "The storyboard has problems. Fix the highlighted scenes and save again.",
  job_not_cancellable: "This video can no longer be cancelled.",
  job_not_deletable: "This video cannot be deleted while it is being made.",
  job_not_revisable: "Only a finished video can be revised.",
  job_not_shareable: "Only a finished video can be shared.",
  share_not_found: "That share link no longer exists.",
  share_rendition_not_found: "That version of the video is not available to share.",
  idempotency_request_in_progress:
    "Your previous attempt is still being processed. Try again in a moment.",
  idempotency_key_reused: "This request was already used. Start the action again.",
};

export const policyRefusalCodes = [
  "policy_weapons",
  "policy_malware",
  "policy_self_harm",
  "policy_abuse",
  "policy_sexual_content",
  "policy_harassment",
  "policy_political_persuasion",
  "policy_personal_data",
  "policy_prompt_injection",
  "policy_prompt_extraction",
  "policy_unsupported_request",
  "policy_output_blocked",
] as const;

export const failureGuidance: Readonly<Record<string, string>> = {
  policy_output_blocked:
    "The video could not be completed safely. Your credits were returned. Try rephrasing your request.",
  llm_unavailable:
    "The writing assistant is unavailable right now. Your credits were returned. Try again in a few minutes.",
  model_output_invalid:
    "The assistant could not produce a usable storyboard. Your credits were returned. Try again or rephrase your request.",
  budget_exceeded:
    "This video needed more work than one video may use. Your credits were returned. Try a shorter video or a simpler topic.",
  tts_failed:
    "Narration could not be recorded. Your credits were returned. Try again or choose another voice.",
  no_style_skill: "The chosen style is no longer available. Pick another style and try again.",
  composition_invalid:
    "The scenes could not be assembled into a video. Your credits were returned. Try again.",
  approval_expired:
    "The storyboard waited too long for review and the video was cancelled. Your credits were returned.",
  stalled: "The video stopped making progress and was stopped. Your credits were returned.",
  user_cancelled: "You cancelled this video. Your credits were returned.",
};

export const isPolicyRefusal = (code: string | null | undefined): boolean =>
  code !== null &&
  code !== undefined &&
  code.startsWith("policy_") &&
  code !== "policy_output_blocked";

export const generationErrorMessage = (error: unknown): string => {
  const normalized = ApiError.from(error);
  if (normalized.code === "input_refused") {
    return (
      normalized.detail ??
      "Motionile could not use this request. Describe the topic you want explained and try again."
    );
  }
  if (normalized.code === "insufficient_credits") {
    const shortfall = normalized.extensions["shortfall"];
    return typeof shortfall === "number" && shortfall > 0
      ? `You need ${String(shortfall)} more credits for this video.`
      : (generationErrorMessages["insufficient_credits"] ?? "");
  }
  if (normalized.code === "too_many_active_jobs") {
    const limit = normalized.extensions["limit"];
    return typeof limit === "number"
      ? `You can have ${String(limit)} videos in progress at once. Wait for one to finish or cancel it first.`
      : (generationErrorMessages["too_many_active_jobs"] ?? "");
  }
  return generationErrorMessages[normalized.code] ?? authErrorMessage(error);
};

export interface FailureExplanation {
  title: string;
  message: string;
  refusal: boolean;
}

export const explainFailure = (
  status: "failed" | "cancelled",
  code: string | null,
  title: string | null,
  message: string | null,
): FailureExplanation => {
  if (status === "cancelled") {
    return {
      title: "Video cancelled",
      message:
        message ??
        (code === null ? undefined : failureGuidance[code]) ??
        "This video was cancelled. Your credits were returned.",
      refusal: false,
    };
  }
  const refusal = isPolicyRefusal(code);
  return {
    title: title ?? (refusal ? "Request not supported" : "The video could not be made"),
    message:
      message ??
      (code === null ? undefined : failureGuidance[code]) ??
      "Something went wrong while making this video. Your credits were returned.",
    refusal,
  };
};

export const isRetryableSubmitError = (error: unknown): boolean => {
  const normalized = ApiError.from(error);
  return normalized.isTransient || normalized.code === "idempotency_request_in_progress";
};
