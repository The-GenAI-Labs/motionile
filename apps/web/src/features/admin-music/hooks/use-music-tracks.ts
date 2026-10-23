"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  activateMusicTrack,
  deactivateMusicTrack,
  listMusicTracks,
  updateMusicTrack,
  uploadMusicTrack,
} from "@/features/admin-music/api/admin-music.api";
import { adminMusicKeys } from "@/features/admin-music/query-keys";
import type {
  MusicActiveAction,
  MusicFilters,
  MusicTrack,
  MusicUpdateInput,
  MusicUploadInput,
} from "@/features/admin-music/types/admin-music.types";
import { useCursorList } from "@/lib/query/use-cursor-list";

const activeActions = {
  activate: activateMusicTrack,
  deactivate: deactivateMusicTrack,
} as const satisfies Record<MusicActiveAction, (trackId: string) => Promise<MusicTrack>>;

export const useMusicTracks = (filters: MusicFilters) =>
  useCursorList(adminMusicKeys.trackList(filters), (cursor) => listMusicTracks(filters, cursor));

export const useUploadMusicTrack = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: MusicUploadInput) => uploadMusicTrack(input),
    onSuccess: () => client.invalidateQueries({ queryKey: adminMusicKeys.tracks() }),
  });
};

export const useUpdateMusicTrack = (trackId: string) => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: MusicUpdateInput) => updateMusicTrack(trackId, input),
    onSuccess: () => client.invalidateQueries({ queryKey: adminMusicKeys.tracks() }),
  });
};

export const useSetMusicTrackActive = (trackId: string) => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (action: MusicActiveAction) => activeActions[action](trackId),
    onSuccess: () => client.invalidateQueries({ queryKey: adminMusicKeys.tracks() }),
  });
};
