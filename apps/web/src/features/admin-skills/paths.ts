export const adminSkillsPaths = {
  root: "/admin/skills",
  skill: (slug: string) => `/admin/skills/${slug}` as const,
} as const;
