import { authErrorMessage } from "@/features/auth/errors";
import { ApiError } from "@/lib/api/api-error";

export const adminMusicGuidance: Readonly<Record<string, string>> = {
  music_track_unavailable: "This track is inactive or no longer available. Activate it first.",
  music_track_not_found: "This track no longer exists. Reload the list.",
  music_update_empty: "Change at least one field before saving.",
  music_not_audio: "The file is not audio. Choose an MP3, M4A, WAV, FLAC or OGG file.",
  music_too_large: "The audio file is larger than 50 MB. Choose a smaller file.",
  music_too_short: "The audio is shorter than 5 seconds. Choose a longer track.",
  music_too_long: "The audio is longer than 15 minutes. Choose a shorter track.",
  music_video_stream: "The file contains a video stream. Upload an audio-only file.",
  music_unsupported_format: "This audio format is not supported. Convert it to MP3, M4A or WAV.",
  music_unreadable: "The audio could not be read. The file may be corrupt.",
  music_transcode_failed: "The audio could not be converted. Try another export of the track.",
  forbidden: "Your account is not allowed to manage the music library.",
  payload_too_large: "The audio file is larger than 50 MB. Choose a smaller file.",
  validation_failed: "Check the highlighted fields and try again.",
};

export const adminMusicErrorMessage = (error: unknown): string => {
  const normalized = ApiError.from(error);
  if (normalized.status === 413) {
    return adminMusicGuidance["music_too_large"] ?? authErrorMessage(error);
  }
  return adminMusicGuidance[normalized.code] ?? authErrorMessage(error);
};
