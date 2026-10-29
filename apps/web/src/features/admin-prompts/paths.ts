export const adminPromptsPaths = {
  root: "/admin/prompts",
  template: (key: string) => `/admin/prompts/${encodeURIComponent(key)}` as const,
} as const;
