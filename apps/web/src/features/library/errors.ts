import { authErrorMessage } from "@/features/auth/errors";
import { ApiError } from "@/lib/api/api-error";

export const libraryGuidance: Readonly<Record<string, string>> = {
  job_not_found: "This video no longer exists. Reload your library.",
  job_not_deletable: "A video that is still being made cannot be deleted. Cancel it first.",
  job_not_shareable: "Only a finished video can be shared.",
  share_rendition_not_found: "That version of the video is not ready. Choose another one.",
  share_not_found: "This link no longer works.",
  validation_failed: "Check your choices and try again.",
  rate_limited: "Too many requests. Wait a moment and try again.",
};

export const libraryErrorMessage = (error: unknown): string => {
  const normalized = ApiError.from(error);
  return libraryGuidance[normalized.code] ?? authErrorMessage(error);
};
