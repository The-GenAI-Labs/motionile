import type { LibraryFilters } from "@/features/library/types/library.types";

export const libraryKeys = {
  all: ["library"] as const,
  lists: () => [...libraryKeys.all, "list"] as const,
  list: (filters: LibraryFilters) => [...libraryKeys.lists(), filters] as const,
  recent: () => [...libraryKeys.all, "recent"] as const,
  activeJobs: () => [...libraryKeys.all, "active-jobs"] as const,
  mediaSession: () => [...libraryKeys.all, "media-session"] as const,
  renders: () => [...libraryKeys.all, "renders"] as const,
  render: (renderId: string) => [...libraryKeys.renders(), "detail", renderId] as const,
  renditions: (renderId: string) => [...libraryKeys.renders(), "renditions", renderId] as const,
};
