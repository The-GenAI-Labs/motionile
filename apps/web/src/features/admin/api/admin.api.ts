import * as contract from "@motionile/api-contract";
import type { z } from "zod";

import { apiClient } from "@/lib/api/client";

export const roles = async () =>
  contract.zAccessCatalogResponse.parse(
    (await apiClient.get<unknown>("/v1/admin/roles", { authenticated: true })).data,
  );
export const createRole = async (input: z.input<typeof contract.zRoleCreateRequest>) =>
  contract.zRoleResponse.parse(
    (
      await apiClient.post<unknown>("/v1/admin/roles", contract.zRoleCreateRequest.parse(input), {
        authenticated: true,
      })
    ).data,
  );
export const updateRole = async (
  roleId: string,
  input: z.input<typeof contract.zRoleUpdateRequest>,
) =>
  contract.zRoleResponse.parse(
    (
      await apiClient.patch<unknown>(
        `/v1/admin/roles/${roleId}`,
        contract.zRoleUpdateRequest.parse(input),
        { authenticated: true },
      )
    ).data,
  );
export const deleteRole = async (roleId: string) => {
  await apiClient.delete(`/v1/admin/roles/${roleId}`, { authenticated: true });
};
export interface AdminUserParams {
  search?: string;
  status?: "pending_verification" | "active" | "suspended" | "deleted";
  role?: string;
  createdFrom?: string;
  createdTo?: string;
  sort?: "created_desc" | "created_asc";
}
export const adminUsers = async (params: AdminUserParams) =>
  contract.zAdminUserListResponse.parse(
    (await apiClient.get<unknown>("/v1/admin/users", { authenticated: true, params })).data,
  );
export const adminUser = async (userId: string) =>
  contract.zAdminUserDetailResponse.parse(
    (await apiClient.get<unknown>(`/v1/admin/users/${userId}`, { authenticated: true })).data,
  );
const userAction = async (
  userId: string,
  action: "suspend" | "unsuspend" | "restore" | "sign-out",
) => {
  await apiClient.post(`/v1/admin/users/${userId}/${action}`, undefined, { authenticated: true });
};
export const suspendUser = (userId: string) => userAction(userId, "suspend");
export const unsuspendUser = (userId: string) => userAction(userId, "unsuspend");
export const restoreUser = (userId: string) => userAction(userId, "restore");
export const forceSignOutUser = (userId: string) => userAction(userId, "sign-out");
export const assignUserRole = async (userId: string, roleId: string) => {
  await apiClient.post(
    `/v1/admin/users/${userId}/roles`,
    contract.zUserRoleMutationRequest.parse({ roleId }),
    { authenticated: true },
  );
};
export const removeUserRole = async (userId: string, roleId: string) => {
  await apiClient.delete(`/v1/admin/users/${userId}/roles/${roleId}`, { authenticated: true });
};
export const analytics = async () =>
  contract.zAnalyticsResponse.parse(
    (await apiClient.get<unknown>("/v1/admin/analytics", { authenticated: true })).data,
  );
export interface AuditParams {
  actorUserId?: string;
  action?: string;
  targetType?: string;
  targetId?: string;
  createdFrom?: string;
  createdTo?: string;
}
export const auditEntries = async (params: AuditParams) =>
  contract.zAuditListResponse.parse(
    (await apiClient.get<unknown>("/v1/admin/audit", { authenticated: true, params })).data,
  );
export const adminCatalogTree = async () =>
  contract.zAdminCatalogTreeResponse.parse(
    (await apiClient.get<unknown>("/v1/admin/catalog/tree", { authenticated: true })).data,
  );
export const createCategory = async (input: z.input<typeof contract.zCategoryWriteRequest>) =>
  contract.zCatalogCategoryResponse.parse(
    (
      await apiClient.post<unknown>(
        "/v1/admin/catalog/categories",
        contract.zCategoryWriteRequest.parse(input),
        { authenticated: true },
      )
    ).data,
  );
export const updateCategory = async (
  categoryId: string,
  input: z.input<typeof contract.zCategoryUpdateRequest>,
) =>
  contract.zCatalogCategoryResponse.parse(
    (
      await apiClient.put<unknown>(
        `/v1/admin/catalog/categories/${categoryId}`,
        contract.zCategoryUpdateRequest.parse(input),
        { authenticated: true },
      )
    ).data,
  );
export const createTopic = async (input: z.input<typeof contract.zTopicWriteRequest>) =>
  contract.zCatalogTopicResponse.parse(
    (
      await apiClient.post<unknown>(
        "/v1/admin/catalog/topics",
        contract.zTopicWriteRequest.parse(input),
        { authenticated: true },
      )
    ).data,
  );
export const updateTopic = async (
  topicId: string,
  input: z.input<typeof contract.zTopicUpdateRequest>,
) =>
  contract.zCatalogTopicResponse.parse(
    (
      await apiClient.put<unknown>(
        `/v1/admin/catalog/topics/${topicId}`,
        contract.zTopicUpdateRequest.parse(input),
        { authenticated: true },
      )
    ).data,
  );
export const reorderCatalog = async (input: z.input<typeof contract.zCatalogReorderRequest>) => {
  await apiClient.put("/v1/admin/catalog/reorder", contract.zCatalogReorderRequest.parse(input), {
    authenticated: true,
  });
};
