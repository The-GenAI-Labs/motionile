import * as contract from "@motionile/api-contract";
import { z } from "zod";

import type {
  MusicFilters,
  MusicUpdateInput,
  MusicUploadInput,
} from "@/features/admin-music/types/admin-music.types";
import { apiClient } from "@/lib/api/client";

export const MUSIC_PAGE_SIZE = 25;
export const MUSIC_UPLOAD_TIMEOUT_MS = 180_000;

const BASE = "/v1/admin/music";

const pathId = (value: string): string => z.uuid().parse(value);

const uploadMetadataSchema = contract.zBodyAdminMusicUploadMusicTrack.omit({ file: true });

export const listMusicTracks = async (filters: MusicFilters, cursor?: string) =>
  contract.zAdminMusicListMusicTracksResponse.parse(
    (
      await apiClient.get<unknown>(BASE, {
        authenticated: true,
        params: contract.zAdminMusicListMusicTracksQuery.parse({
          ...filters,
          cursor,
          limit: MUSIC_PAGE_SIZE,
        }),
      })
    ).data,
  );

export const uploadMusicTrack = async ({ file, metadata }: MusicUploadInput) => {
  const parsed = uploadMetadataSchema.parse(metadata);
  const body = new FormData();
  body.set("file", file);
  body.set("title", parsed.title);
  body.set("mood", parsed.mood);
  body.set("licenseName", parsed.licenseName);
  body.set("licenseUrl", parsed.licenseUrl);
  body.set("activate", String(parsed.activate));
  if (parsed.bpm !== undefined && parsed.bpm !== null) {
    body.set("bpm", String(parsed.bpm));
  }
  if (parsed.attributionText !== undefined && parsed.attributionText !== null) {
    body.set("attributionText", parsed.attributionText);
  }
  return contract.zAdminMusicUploadMusicTrackResponse.parse(
    (
      await apiClient.post<unknown>(BASE, body, {
        authenticated: true,
        timeout: MUSIC_UPLOAD_TIMEOUT_MS,
        headers: { "Content-Type": "multipart/form-data" },
      })
    ).data,
  );
};

export const updateMusicTrack = async (trackId: string, input: MusicUpdateInput) =>
  contract.zAdminMusicUpdateMusicTrackResponse.parse(
    (
      await apiClient.patch<unknown>(
        `${BASE}/${pathId(trackId)}`,
        contract.zAdminMusicUpdateMusicTrackBody.parse(input),
        { authenticated: true },
      )
    ).data,
  );

export const activateMusicTrack = async (trackId: string) =>
  contract.zAdminMusicActivateMusicTrackResponse.parse(
    (
      await apiClient.post<unknown>(`${BASE}/${pathId(trackId)}/activate`, undefined, {
        authenticated: true,
      })
    ).data,
  );

export const deactivateMusicTrack = async (trackId: string) =>
  contract.zAdminMusicDeactivateMusicTrackResponse.parse(
    (
      await apiClient.post<unknown>(`${BASE}/${pathId(trackId)}/deactivate`, undefined, {
        authenticated: true,
      })
    ).data,
  );
