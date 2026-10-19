"use client";

import type { ReactNode } from "react";

import { useCurrentUser } from "@/features/auth/hooks/use-current-user";
import { hasPermissions, type PermissionMatchMode } from "@/lib/auth/permissions";

export { hasPermissions, type PermissionMatchMode };

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
