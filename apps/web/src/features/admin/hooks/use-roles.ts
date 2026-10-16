"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { createRole, deleteRole, roles, updateRole } from "@/features/admin/api/admin.api";
import { adminKeys } from "@/features/admin/query-keys";

export const useRoles = () => useQuery({ queryKey: adminKeys.roles(), queryFn: roles });
const useInvalidateRoles = () => {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: adminKeys.roles() });
};
export const useCreateRole = () => {
  const invalidate = useInvalidateRoles();
  return useMutation({ mutationFn: createRole, onSuccess: invalidate });
};
export const useUpdateRole = () => {
  const invalidate = useInvalidateRoles();
  return useMutation({
    mutationFn: ({ roleId, input }: { roleId: string; input: Parameters<typeof updateRole>[1] }) =>
      updateRole(roleId, input),
    onSuccess: invalidate,
  });
};
export const useDeleteRole = () => {
  const invalidate = useInvalidateRoles();
  return useMutation({ mutationFn: deleteRole, onSuccess: invalidate });
};
