import {
  describeActivationBlock,
  readActivationBlock,
} from "@/features/admin-prompts/schemas/admin-prompts.schema";
import { authErrorMessage } from "@/features/auth/errors";
import { ApiError } from "@/lib/api/api-error";

export const adminPromptsGuidance: Readonly<Record<string, string>> = {
  prompt_template_not_found: "This prompt template does not exist. Return to the list.",
  prompt_version_not_found: "This version does not exist. Reload the versions.",
  eval_run_not_found: "This evaluation run does not exist. Reload the list.",
  prompt_draft_invalid: "The draft is not valid. Check the text and the variable names.",
  prompt_version_exists: "A version with exactly this text already exists. Change the text first.",
  activation_conflict: "The active version changed while you were working. Reload and try again.",
  no_previous_version: "There is no earlier version to roll back to.",
  unknown_suite: "That evaluation suite does not exist. Choose one from the list.",
  eval_run_invalid: "The evaluation run is not valid. Check the suite and the selected versions.",
  forbidden: "Your account is not allowed to do this.",
  validation_failed: "Check the highlighted fields and try again.",
  rate_limited: "Too many changes in a short time. Wait a moment and try again.",
};

export const adminPromptsErrorMessage = (error: unknown): string => {
  const normalized = ApiError.from(error);
  if (normalized.code === "activation_blocked") {
    return describeActivationBlock(readActivationBlock(normalized.extensions));
  }
  return adminPromptsGuidance[normalized.code] ?? authErrorMessage(error);
};
