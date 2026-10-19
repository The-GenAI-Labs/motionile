export type PermissionMatchMode = "all" | "any";

export const hasPermissions = (
  required: readonly string[],
  granted: readonly string[],
  mode: PermissionMatchMode = "all",
): boolean => {
  if (required.length === 0) {
    return true;
  }
  const grantedSet = new Set(granted);
  return mode === "all"
    ? required.every((permission) => grantedSet.has(permission))
    : required.some((permission) => grantedSet.has(permission));
};
