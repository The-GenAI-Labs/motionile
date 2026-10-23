import { voiceErrorMessage } from "@/features/voices/errors";
import { ApiError } from "@/lib/api/api-error";

const adminVoiceGuidance: Readonly<Record<string, string>> = {
  voice_provider_unavailable:
    "The voice provider is unavailable. Nothing was changed; try again shortly.",
  voice_preview_failed:
    "The preview could not be generated, so the voice was not changed. Try again shortly.",
  voice_not_found: "This voice no longer exists. Reload the list.",
  voice_update_empty: "Change at least one field before saving.",
  forbidden: "Your account is not allowed to manage the voice catalog.",
};

export const adminVoiceErrorMessage = (error: unknown): string =>
  adminVoiceGuidance[ApiError.from(error).code] ?? voiceErrorMessage(error);
