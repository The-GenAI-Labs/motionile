import * as contract from "@motionile/api-contract";
import type { z } from "zod";

import { apiClient } from "@/lib/api/client";

export const userProfile = async () =>
  contract.zUserProfileResponse.parse(
    (await apiClient.get<unknown>("/v1/users/me", { authenticated: true })).data,
  );
export const updateUserProfile = async (
  input: z.input<typeof contract.zUserProfileUpdateRequest>,
) =>
  contract.zUserProfileResponse.parse(
    (
      await apiClient.patch<unknown>(
        "/v1/users/me",
        contract.zUserProfileUpdateRequest.parse(input),
        { authenticated: true },
      )
    ).data,
  );
export const uploadAvatar = async (file: File) => {
  const body = new FormData();
  body.set("file", file);
  return contract.zAvatarResponse.parse(
    (await apiClient.put<unknown>("/v1/users/me/avatar", body, { authenticated: true })).data,
  );
};
export const removeAvatar = async () => {
  await apiClient.delete("/v1/users/me/avatar", { authenticated: true });
};
export const addContact = async (input: z.input<typeof contract.zContactAddRequest>) =>
  contract.zContactChallengeResponse.parse(
    (
      await apiClient.post<unknown>(
        "/v1/users/me/contacts",
        contract.zContactAddRequest.parse(input),
        { authenticated: true },
      )
    ).data,
  );
export const verifyContact = async (input: z.input<typeof contract.zContactVerifyRequest>) =>
  contract.zUserContactResponse.parse(
    (
      await apiClient.post<unknown>(
        "/v1/users/me/contacts/verify",
        contract.zContactVerifyRequest.parse(input),
        { authenticated: true },
      )
    ).data,
  );
export const setPrimaryContact = async (contactId: string) =>
  contract.zUserContactResponse.parse(
    (
      await apiClient.put<unknown>(`/v1/users/me/contacts/${contactId}/primary`, undefined, {
        authenticated: true,
      })
    ).data,
  );
export const removeContact = async (contactId: string) => {
  await apiClient.delete(`/v1/users/me/contacts/${contactId}`, { authenticated: true });
};
export const userPreferences = async () =>
  contract.zUserPreferencesResponse.parse(
    (await apiClient.get<unknown>("/v1/users/me/preferences", { authenticated: true })).data,
  );
export const updateUserPreferences = async (
  input: z.input<typeof contract.zUserPreferencesUpdateRequest>,
) =>
  contract.zUserPreferencesResponse.parse(
    (
      await apiClient.put<unknown>(
        "/v1/users/me/preferences",
        contract.zUserPreferencesUpdateRequest.parse(input),
        { authenticated: true },
      )
    ).data,
  );
export const requestExport = async () =>
  contract.zExportResponse.parse(
    (await apiClient.post<unknown>("/v1/users/me/export", undefined, { authenticated: true })).data,
  );
export const requestAccountDeletion = async () =>
  contract.zContactChallengeResponse.parse(
    (
      await apiClient.post<unknown>("/v1/users/me/delete/request", undefined, {
        authenticated: true,
      })
    ).data,
  );
export const confirmAccountDeletion = async (
  input: z.input<typeof contract.zAccountDeletionConfirmRequest>,
) => {
  await apiClient.post(
    "/v1/users/me/delete/confirm",
    contract.zAccountDeletionConfirmRequest.parse(input),
    { authenticated: true },
  );
};
