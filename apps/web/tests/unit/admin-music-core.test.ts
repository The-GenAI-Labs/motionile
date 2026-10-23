import { beforeEach, describe, expect, it, vi } from "vitest";

import { uploadMusicTrack } from "@/features/admin-music/api/admin-music.api";
import { adminMusicErrorMessage } from "@/features/admin-music/errors";
import { toMusicFilters } from "@/features/admin-music/hooks/use-music-filters";
import { adminMusicKeys } from "@/features/admin-music/query-keys";
import {
  emptyTrackFormValues,
  hasUpdateChanges,
  MUSIC_MAX_BYTES,
  toUpdateInput,
  toUploadInput,
  trackFormSchema,
  trackFormValues,
  uploadFormSchema,
} from "@/features/admin-music/schemas/admin-music.schema";
import { ApiError } from "@/lib/api/api-error";
import { formatDurationMs } from "@/lib/utils/format";

import { inactiveTrack, musicTrack } from "./admin-music-fixtures";

const client = vi.hoisted(() => ({ post: vi.fn() }));

vi.mock("@/lib/api/client", () => ({ apiClient: client }));

const valid = {
  ...emptyTrackFormValues,
  title: "Quiet Orbit",
  mood: "calm",
  licenseName: "CC BY 4.0",
  licenseUrl: "https://creativecommons.org/licenses/by/4.0/",
};

const audio = (size = 10) => new File([new Uint8Array(size)], "orbit.mp3", { type: "audio/mpeg" });

const problem = (code: string, status: number) =>
  new ApiError({ kind: "http", status, code, title: code, detail: null });

beforeEach(() => {
  vi.clearAllMocks();
});

describe("music form schema", () => {
  it("accepts a complete track and trims text", () => {
    const parsed = trackFormSchema.parse({ ...valid, title: "  Quiet Orbit  ", bpm: " 92 " });

    expect(parsed.title).toBe("Quiet Orbit");
    expect(parsed.bpm).toBe("92");
  });

  it("rejects moods that the API would reject", () => {
    for (const mood of ["", "Calm", "1calm", "a", "calm mood", "x".repeat(41)]) {
      expect(trackFormSchema.safeParse({ ...valid, mood }).success).toBe(false);
    }
    expect(trackFormSchema.safeParse({ ...valid, mood: "lo-fi-2" }).success).toBe(true);
  });

  it("requires an https license url without spaces", () => {
    for (const licenseUrl of ["", "http://example.com/l", "javascript:alert(1)", "https://a b"]) {
      expect(trackFormSchema.safeParse({ ...valid, licenseUrl }).success).toBe(false);
    }
  });

  it("bounds the bpm and allows it to be empty", () => {
    expect(trackFormSchema.safeParse({ ...valid, bpm: "" }).success).toBe(true);
    for (const bpm of ["29", "301", "12.5", "abc", "-90"]) {
      expect(trackFormSchema.safeParse({ ...valid, bpm }).success).toBe(false);
    }
    expect(trackFormSchema.safeParse({ ...valid, bpm: "30" }).success).toBe(true);
    expect(trackFormSchema.safeParse({ ...valid, bpm: "300" }).success).toBe(true);
  });

  it("bounds the text lengths", () => {
    expect(trackFormSchema.safeParse({ ...valid, title: "x".repeat(121) }).success).toBe(false);
    expect(trackFormSchema.safeParse({ ...valid, licenseName: " " }).success).toBe(false);
    expect(trackFormSchema.safeParse({ ...valid, attributionText: "x".repeat(501) }).success).toBe(
      false,
    );
  });

  it("requires an audio file within the size limit only for uploads", () => {
    expect(trackFormSchema.safeParse(valid).success).toBe(true);
    const missing = uploadFormSchema.safeParse(valid);
    expect(missing.success).toBe(false);
    expect(missing.error?.issues[0]?.path).toEqual(["file"]);
    expect(uploadFormSchema.safeParse({ ...valid, file: audio() }).success).toBe(true);
    expect(uploadFormSchema.safeParse({ ...valid, file: audio(0) }).success).toBe(false);
    const huge = audio();
    Object.defineProperty(huge, "size", { value: MUSIC_MAX_BYTES + 1 });
    expect(uploadFormSchema.safeParse({ ...valid, file: huge }).success).toBe(false);
  });
});

describe("music form conversion", () => {
  it("builds the upload input and omits empty optional fields", () => {
    const file = audio();

    expect(toUploadInput({ ...valid, file })).toEqual({
      file,
      metadata: {
        title: "Quiet Orbit",
        mood: "calm",
        licenseName: "CC BY 4.0",
        licenseUrl: "https://creativecommons.org/licenses/by/4.0/",
        activate: false,
      },
    });
    expect(
      toUploadInput({ ...valid, file, bpm: "92", attributionText: "Credit", activate: true })
        .metadata,
    ).toMatchObject({ bpm: 92, attributionText: "Credit", activate: true });
    expect(() => toUploadInput(valid)).toThrow("An audio file is required.");
  });

  it("fills the edit form from a track", () => {
    expect(trackFormValues(musicTrack())).toMatchObject({
      title: "Quiet Orbit",
      bpm: "92",
      attributionText: "Composed by Ada",
    });
    expect(trackFormValues(inactiveTrack)).toMatchObject({ bpm: "", attributionText: "" });
  });

  it("sends only the changed fields and null for cleared optional ones", () => {
    const track = musicTrack();
    const same = trackFormValues(track);

    expect(hasUpdateChanges(toUpdateInput(same, track))).toBe(false);
    expect(toUpdateInput({ ...same, title: "Renamed", mood: "epic" }, track)).toEqual({
      title: "Renamed",
      mood: "epic",
    });
    expect(toUpdateInput({ ...same, bpm: "", attributionText: "" }, track)).toEqual({
      bpm: null,
      attributionText: null,
    });
    expect(toUpdateInput({ ...trackFormValues(inactiveTrack), bpm: "" }, inactiveTrack)).toEqual(
      {},
    );
  });
});

describe("music filters", () => {
  it("applies a valid lowercase mood and the active flag only", () => {
    expect(toMusicFilters({ mood: "", active: null }, "")).toEqual({});
    expect(toMusicFilters({ mood: "", active: false }, "Calm")).toEqual({
      mood: "calm",
      active: false,
    });
    expect(toMusicFilters({ mood: "", active: true }, "not a mood")).toEqual({ active: true });
  });

  it("scopes query keys under the music root and separates filters", () => {
    expect(adminMusicKeys.trackList({ mood: "calm" })).toEqual([
      "admin-music",
      "tracks",
      "list",
      { mood: "calm" },
    ]);
    expect(adminMusicKeys.trackList({})).not.toEqual(adminMusicKeys.trackList({ active: true }));
  });
});

describe("music error messages", () => {
  it("maps every music problem code to guidance", () => {
    expect(adminMusicErrorMessage(problem("music_not_audio", 422))).toMatch(/not audio/);
    expect(adminMusicErrorMessage(problem("music_track_unavailable", 422))).toMatch(/inactive/);
    expect(adminMusicErrorMessage(problem("music_too_short", 422))).toMatch(/5 seconds/);
    expect(adminMusicErrorMessage(problem("music_too_long", 422))).toMatch(/15 minutes/);
    expect(adminMusicErrorMessage(problem("music_video_stream", 422))).toMatch(/video stream/);
    expect(adminMusicErrorMessage(problem("music_unsupported_format", 422))).toMatch(/format/);
    expect(adminMusicErrorMessage(problem("music_unreadable", 422))).toMatch(/corrupt/);
    expect(adminMusicErrorMessage(problem("music_transcode_failed", 422))).toMatch(/converted/);
    expect(adminMusicErrorMessage(problem("music_track_not_found", 404))).toMatch(
      /no longer exists/,
    );
    expect(adminMusicErrorMessage(problem("music_update_empty", 422))).toMatch(/at least one/);
    expect(adminMusicErrorMessage(problem("forbidden", 403))).toMatch(/not allowed/);
  });

  it("treats any 413 as too large and falls back to the shared messages", () => {
    expect(adminMusicErrorMessage(problem("http_error", 413))).toMatch(/50 MB/);
    expect(adminMusicErrorMessage(problem("music_too_large", 413))).toMatch(/50 MB/);
    expect(adminMusicErrorMessage(problem("unknown_code", 500))).toMatch(/Something went wrong/);
    expect(adminMusicErrorMessage(problem("rate_limited", 429))).toMatch(/Please wait/);
  });
});

describe("music upload request", () => {
  it("posts multipart form data with the API field names", async () => {
    client.post.mockResolvedValue({ data: musicTrack() });
    const file = audio();

    await uploadMusicTrack({
      file,
      metadata: {
        title: "Quiet Orbit",
        mood: "calm",
        bpm: 92,
        licenseName: "CC BY 4.0",
        licenseUrl: "https://creativecommons.org/licenses/by/4.0/",
        attributionText: "Composed by Ada",
        activate: true,
      },
    });

    const [url, body, config] = client.post.mock.calls[0] as [
      string,
      FormData,
      { headers: object },
    ];
    expect(url).toBe("/v1/admin/music");
    expect(Object.fromEntries([...body.entries()].filter(([key]) => key !== "file"))).toEqual({
      title: "Quiet Orbit",
      mood: "calm",
      bpm: "92",
      licenseName: "CC BY 4.0",
      licenseUrl: "https://creativecommons.org/licenses/by/4.0/",
      attributionText: "Composed by Ada",
      activate: "true",
    });
    expect((body.get("file") as File).name).toBe("orbit.mp3");
    expect(config.headers).toEqual({ "Content-Type": "multipart/form-data" });
  });

  it("omits optional fields and rejects invalid metadata before sending", async () => {
    client.post.mockResolvedValue({ data: musicTrack() });
    const metadata = {
      title: "Quiet Orbit",
      mood: "calm",
      licenseName: "CC BY 4.0",
      licenseUrl: "https://creativecommons.org/licenses/by/4.0/",
      activate: false,
    };

    await uploadMusicTrack({ file: audio(), metadata });
    const body = (client.post.mock.calls[0] as [string, FormData])[1];
    expect(body.has("bpm")).toBe(false);
    expect(body.has("attributionText")).toBe(false);

    await expect(
      uploadMusicTrack({ file: audio(), metadata: { ...metadata, mood: "Not A Mood" } }),
    ).rejects.toThrow();
    expect(client.post).toHaveBeenCalledTimes(1);
  });
});

describe("duration formatting", () => {
  it("formats milliseconds as minutes and seconds", () => {
    expect(formatDurationMs(0)).toBe("0:00");
    expect(formatDurationMs(5_000)).toBe("0:05");
    expect(formatDurationMs(125_000)).toBe("2:05");
    expect(formatDurationMs(900_000)).toBe("15:00");
    expect(formatDurationMs(-5)).toBe("0:00");
  });
});
