"use client";

import { useQueryClient } from "@tanstack/react-query";

import { adminMusicKeys } from "@/features/admin-music/query-keys";

export const useRefreshMusicTracks = () => {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: adminMusicKeys.tracks() });
};
