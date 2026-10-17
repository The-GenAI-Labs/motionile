"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import * as usersApi from "@/features/users/api/users.api";
import { userKeys } from "@/features/users/query-keys";

export const useUserProfile = () =>
  useQuery({ queryKey: userKeys.profile(), queryFn: usersApi.userProfile });
export const useUserPreferences = () =>
  useQuery({ queryKey: userKeys.preferences(), queryFn: usersApi.userPreferences });
const useInvalidateProfile = () => {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: userKeys.profile() });
};
export const useUpdateProfile = () => {
  const invalidate = useInvalidateProfile();
  return useMutation({ mutationFn: usersApi.updateUserProfile, onSuccess: invalidate });
};
export const useUploadAvatar = () => {
  const invalidate = useInvalidateProfile();
  return useMutation({ mutationFn: usersApi.uploadAvatar, onSuccess: invalidate });
};
export const useRemoveAvatar = () => {
  const invalidate = useInvalidateProfile();
  return useMutation({ mutationFn: usersApi.removeAvatar, onSuccess: invalidate });
};
export const useAddContact = () => useMutation({ mutationFn: usersApi.addContact });
export const useVerifyContact = () => {
  const invalidate = useInvalidateProfile();
  return useMutation({ mutationFn: usersApi.verifyContact, onSuccess: invalidate });
};
export const useSetPrimaryContact = () => {
  const invalidate = useInvalidateProfile();
  return useMutation({ mutationFn: usersApi.setPrimaryContact, onSuccess: invalidate });
};
export const useRemoveContact = () => {
  const invalidate = useInvalidateProfile();
  return useMutation({ mutationFn: usersApi.removeContact, onSuccess: invalidate });
};
export const useUpdatePreferences = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: usersApi.updateUserPreferences,
    onSuccess: (data) => client.setQueryData(userKeys.preferences(), data),
  });
};
export const useRequestExport = () => useMutation({ mutationFn: usersApi.requestExport });
export const useRequestDeletion = () =>
  useMutation({ mutationFn: usersApi.requestAccountDeletion });
export const useConfirmDeletion = () =>
  useMutation({ mutationFn: usersApi.confirmAccountDeletion });
