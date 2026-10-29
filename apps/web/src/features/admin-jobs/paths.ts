export const adminJobsPaths = {
  root: "/admin/jobs",
  job: (jobId: string) => `/admin/jobs/${jobId}` as const,
  user: (userId: string) => `/admin/users/${userId}` as const,
} as const;
