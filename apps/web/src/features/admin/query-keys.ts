export const adminKeys = {
  all: ["admin"] as const,
  roles: () => [...adminKeys.all, "roles"] as const,
  users: (filters: Record<string, string>) => [...adminKeys.all, "users", filters] as const,
  user: (userId: string) => [...adminKeys.all, "user", userId] as const,
  audit: (filters: Record<string, string>) => [...adminKeys.all, "audit", filters] as const,
  analytics: () => [...adminKeys.all, "analytics"] as const,
  catalog: () => [...adminKeys.all, "catalog"] as const,
};
