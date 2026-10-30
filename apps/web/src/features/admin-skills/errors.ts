import { authErrorMessage } from "@/features/auth/errors";
import { ApiError } from "@/lib/api/api-error";

export const adminSkillsGuidance: Readonly<Record<string, string>> = {
  skill_not_found: "This skill does not exist. Return to the list.",
  skill_embedding_unavailable:
    "The embedding provider is unavailable, so descriptions could not be embedded. Try the reseed again shortly.",
  skill_library_invalid:
    "The shipped skill library failed its checks, so nothing was changed. Fix the library and redeploy.",
  skill_embedding_dimensions:
    "The embedding model returned vectors of an unexpected size. Check the embedding settings.",
  forbidden: "Your account is not allowed to manage system skills.",
  rate_limited: "Too many reseeds in a short time. Wait a moment and try again.",
};

export const adminSkillsErrorMessage = (error: unknown): string => {
  const normalized = ApiError.from(error);
  return adminSkillsGuidance[normalized.code] ?? authErrorMessage(error);
};
