export const authKeys = {
  all: ["auth"] as const,
  me: () => [...authKeys.all, "me"] as const,
  sessions: () => [...authKeys.all, "sessions"] as const,
};
