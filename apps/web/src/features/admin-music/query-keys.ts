import type { MusicFilters } from "@/features/admin-music/types/admin-music.types";

export const adminMusicKeys = {
  all: ["admin-music"] as const,
  tracks: () => [...adminMusicKeys.all, "tracks"] as const,
  trackList: (filters: MusicFilters) => [...adminMusicKeys.tracks(), "list", filters] as const,
};
