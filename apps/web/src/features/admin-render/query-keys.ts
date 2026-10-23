export const adminRenderKeys = {
  all: ["admin-render"] as const,
  golden: () => [...adminRenderKeys.all, "golden"] as const,
  musicTracks: () => [...adminRenderKeys.all, "music-tracks"] as const,
  renders: () => [...adminRenderKeys.all, "renders"] as const,
  render: (renderId: string) => [...adminRenderKeys.renders(), renderId] as const,
};
