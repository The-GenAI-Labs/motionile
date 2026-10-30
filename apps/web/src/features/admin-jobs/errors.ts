import { authErrorMessage } from "@/features/auth/errors";
import { ApiError } from "@/lib/api/api-error";

export const adminJobsGuidance: Readonly<Record<string, string>> = {
  job_not_found: "This job no longer exists. Return to the list and pick another one.",
  forbidden: "Your account is not allowed to read every user's jobs.",
  validation_failed: "Check the filters and try again.",
  rate_limited: "Too many requests. Wait a moment and try again.",
};

export const adminJobsErrorMessage = (error: unknown): string => {
  const normalized = ApiError.from(error);
  return adminJobsGuidance[normalized.code] ?? authErrorMessage(error);
};
