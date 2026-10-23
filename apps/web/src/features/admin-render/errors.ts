import { authErrorMessage } from "@/features/auth/errors";
import { ApiError } from "@/lib/api/api-error";

export const renderFailureGuidance: Readonly<Record<string, string>> = {
  network_violation:
    "The composition tried to load something from the network. Compositions must be self-contained: inline every script, style, font and image.",
  timeout:
    "The composition took too long to load or to produce a frame. Look for infinite loops, heavy work in the first frame or a ready signal that never resolves.",
  page_error:
    "The composition threw a JavaScript error while rendering. Open it in a browser console to find the failing line.",
  browser_crash:
    "The browser ran out of memory or crashed while capturing. Simplify the composition or reduce the number of large elements.",
  invalid_composition:
    "The composition does not follow the contract. Check that the scene elements match the narration scenes and that the runtime API is used correctly.",
  validation_failed:
    "The composition has layout or timing errors. See the validation report below for each issue, with its scene, time and selector.",
  duration_limit_exceeded:
    "The narration is longer than the maximum of 120 seconds. Shorten the scene text or the uploaded audio.",
  insufficient_disk:
    "The render worker is low on disk space. Try again later or ask an operator to free space.",
  tts_failed:
    "Speech could not be synthesized. Check the chosen voice and the scene text, then try again.",
  output_check_failed:
    "The rendered video failed the output check. Try again; if it repeats, the encoder settings or the composition duration may be at fault.",
  music_track_unavailable:
    "The chosen music track is no longer active. Pick another track or render without music.",
  render_stalled:
    "The render stopped making progress and was failed automatically. The worker may have crashed; try again.",
};

export const renderStatusGuidance: Readonly<Record<string, string>> = {
  cancelled: "This render was cancelled before it finished.",
};

export const renderFailureMessage = (code: string | null | undefined): string =>
  (code ? renderFailureGuidance[code] : undefined) ??
  "The render failed for a reason that is not listed. Check the error message and the server logs.";

export const adminRenderGuidance: Readonly<Record<string, string>> = {
  composition_too_large: "The composition is larger than 4 MB. Remove embedded assets.",
  render_upload_too_large: "The upload is too large. Use smaller audio files.",
  composition_not_utf8: "The composition must be a UTF-8 encoded text file.",
  multipart_required: "The request could not be built. Reload the page and try again.",
  malformed_multipart: "The upload was malformed. Try again.",
  duplicate_part: "The upload contained a duplicate part. Try again.",
  render_options_invalid: "The render options were rejected. Check them and try again.",
  render_audio_rejected: "An uploaded audio file was rejected.",
  voice_not_available: "That voice is not available. Choose another voice.",
  music_track_unavailable: "That music track is not active. Choose another track or none.",
  golden_not_found: "That golden composition no longer exists. Reload the page.",
  render_not_found: "This render does not exist or belongs to another account.",
  rate_limited: "You are starting renders too quickly. Wait a little and try again.",
  forbidden: "Your account is not allowed to use the render test bed.",
  service_unavailable: "The render service is unavailable. Try again shortly.",
  validation_failed: "Check the form and try again.",
  payload_too_large: "The upload is too large. Use a smaller composition or audio files.",
};

const detailCodes = new Set(["render_audio_rejected", "render_options_invalid"]);

export const adminRenderErrorMessage = (error: unknown): string => {
  const normalized = ApiError.from(error);
  if (detailCodes.has(normalized.code) && normalized.detail) {
    return normalized.detail;
  }
  if (normalized.code === "rate_limited" && normalized.retryAfterSeconds !== null) {
    return `You are starting renders too quickly. Try again in ${String(normalized.retryAfterSeconds)} seconds.`;
  }
  const guidance = adminRenderGuidance[normalized.code];
  if (guidance !== undefined) {
    return guidance;
  }
  return normalized.status === 413
    ? (adminRenderGuidance["payload_too_large"] ?? authErrorMessage(error))
    : authErrorMessage(error);
};
