"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import * as adminApi from "@/features/admin/api/admin.api";
import { adminKeys } from "@/features/admin/query-keys";

const userParams = (filters: Record<string, string>): adminApi.AdminUserParams => {
  const params: adminApi.AdminUserParams = {
    sort: filters["sort"] === "created_at" ? "created_asc" : "created_desc",
  };
  if (filters["q"]) params.search = filters["q"];
  if (filters["status"])
    params.status = filters["status"] as NonNullable<adminApi.AdminUserParams["status"]>;
  if (filters["role"]) params.role = filters["role"];
  if (filters["from"]) params.createdFrom = filters["from"];
  if (filters["to"]) params.createdTo = filters["to"];
  return params;
};
export const useAdminUsers = (filters: Record<string, string>) =>
  useQuery({
    queryKey: adminKeys.users(filters),
    queryFn: () => adminApi.adminUsers(userParams(filters)),
  });
export const useAdminUser = (userId: string) =>
  useQuery({ queryKey: adminKeys.user(userId), queryFn: () => adminApi.adminUser(userId) });
export const useAdminUserAction = (userId: string) => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (action: "suspend" | "unsuspend" | "restore" | "sign-out") =>
      ({
        suspend: adminApi.suspendUser,
        unsuspend: adminApi.unsuspendUser,
        restore: adminApi.restoreUser,
        "sign-out": adminApi.forceSignOutUser,
      })[action](userId),
    onSuccess: () => client.invalidateQueries({ queryKey: adminKeys.user(userId) }),
  });
};
export const useAssignRole = (userId: string) => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (roleId: string) => adminApi.assignUserRole(userId, roleId),
    onSuccess: () => client.invalidateQueries({ queryKey: adminKeys.user(userId) }),
  });
};
export const useRemoveRole = (userId: string) => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (roleId: string) => adminApi.removeUserRole(userId, roleId),
    onSuccess: () => client.invalidateQueries({ queryKey: adminKeys.user(userId) }),
  });
};
