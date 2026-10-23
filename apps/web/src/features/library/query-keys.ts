export const libraryKeys = {
  all: ["library"] as const,
  mediaSession: () => [...libraryKeys.all, "media-session"] as const,
  renders: () => [...libraryKeys.all, "renders"] as const,
  render: (renderId: string) => [...libraryKeys.renders(), "detail", renderId] as const,
  renditions: (renderId: string) => [...libraryKeys.renders(), "renditions", renderId] as const,
};
