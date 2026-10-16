export const platformKeys = {
  all: ["platform"] as const,
  flags: () => [...platformKeys.all, "flags"] as const,
  publicSettings: () => [...platformKeys.all, "public-settings"] as const,
  adminFlags: () => [...platformKeys.all, "admin-flags"] as const,
  settings: () => [...platformKeys.all, "settings"] as const,
};
