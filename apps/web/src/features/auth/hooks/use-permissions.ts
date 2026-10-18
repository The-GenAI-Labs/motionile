"use client";

import { useCurrentUser } from "@/features/auth/hooks/use-current-user";

export const usePermissions = () => {
  const currentUser = useCurrentUser();
  const granted = currentUser.data?.permissions ?? [];
  return {
    isPending: currentUser.isPending,
    can: (permission: string): boolean => granted.includes(permission),
  };
};
