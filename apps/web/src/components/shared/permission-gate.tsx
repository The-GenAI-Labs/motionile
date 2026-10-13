import type { ReactNode } from "react";

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

interface PermissionGateProps {
  required: readonly string[];
  granted: readonly string[];
  mode?: PermissionMatchMode;
  fallback?: ReactNode;
  children: ReactNode;
}

export function PermissionGate({
  required,
  granted,
  mode = "all",
  fallback = null,
  children,
}: PermissionGateProps) {
  return hasPermissions(required, granted, mode) ? children : fallback;
}
