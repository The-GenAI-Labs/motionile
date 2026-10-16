"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  adminFlags,
  adminSettings,
  createFlag,
  deleteFlag,
  updateFlag,
  updateSetting,
} from "@/features/platform/api/platform.api";
import { platformKeys } from "@/features/platform/query-keys";

export const useAdminSettings = () =>
  useQuery({ queryKey: platformKeys.settings(), queryFn: adminSettings });
type SettingValue = Parameters<typeof updateSetting>[1]["value"];
export const useUpdateSetting = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ key, value, version }: { key: string; value: SettingValue; version: number }) =>
      updateSetting(key, { value, version }),
    onSuccess: () => client.invalidateQueries({ queryKey: platformKeys.settings() }),
  });
};
export const useAdminFlags = () =>
  useQuery({ queryKey: platformKeys.adminFlags(), queryFn: adminFlags });
export const useUpdateFlag = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ key, input }: { key: string; input: Parameters<typeof updateFlag>[1] }) =>
      updateFlag(key, input),
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: platformKeys.adminFlags() }),
        client.invalidateQueries({ queryKey: platformKeys.flags() }),
      ]),
  });
};
export const useCreateFlag = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: createFlag,
    onSuccess: () => client.invalidateQueries({ queryKey: platformKeys.adminFlags() }),
  });
};
export const useDeleteFlag = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ key, version }: { key: string; version: number }) => deleteFlag(key, version),
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: platformKeys.adminFlags() }),
        client.invalidateQueries({ queryKey: platformKeys.flags() }),
      ]),
  });
};
