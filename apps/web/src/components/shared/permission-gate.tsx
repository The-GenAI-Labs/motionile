"use client";

import type { ReactNode } from "react";

import { useCurrentUser } from "@/features/auth/hooks/use-current-user";

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
  granted?: readonly string[];
  mode?: PermissionMatchMode;
  fallback?: ReactNode;
  children: ReactNode;
}

function SessionPermissionGate({
  required,
  mode = "all",
  fallback = null,
  children,
}: Omit<PermissionGateProps, "granted">) {
  const currentUser = useCurrentUser();
  if (currentUser.isPending) {
    return null;
  }
  const permissions = currentUser.data?.permissions ?? [];
  return hasPermissions(required, permissions, mode) ? children : fallback;
}

export function PermissionGate({ granted, ...props }: PermissionGateProps) {
  if (granted !== undefined) {
    return hasPermissions(props.required, granted, props.mode)
      ? props.children
      : (props.fallback ?? null);
  }
  return <SessionPermissionGate {...props} />;
}
