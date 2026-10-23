"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  listAdminVoices,
  regenerateVoicePreview,
  syncVoices,
  updateAdminVoice,
} from "@/features/admin-voices/api/admin-voices.api";
import { adminVoiceKeys } from "@/features/admin-voices/query-keys";
import type {
  AdminVoiceFilters,
  AdminVoiceUpdateInput,
} from "@/features/admin-voices/types/admin-voices.types";
import { voiceKeys } from "@/features/voices/query-keys";
import { useCursorList } from "@/lib/query/use-cursor-list";

const useInvalidateCatalog = () => {
  const client = useQueryClient();
  return () =>
    Promise.all([
      client.invalidateQueries({ queryKey: adminVoiceKeys.lists() }),
      client.invalidateQueries({ queryKey: voiceKeys.all }),
    ]);
};

export const useAdminVoices = (filters: AdminVoiceFilters) =>
  useCursorList(adminVoiceKeys.list(filters), (cursor) => listAdminVoices(filters, cursor));

export const useSyncVoices = () => {
  const invalidate = useInvalidateCatalog();
  return useMutation({ mutationFn: syncVoices, onSuccess: invalidate });
};

export const useUpdateAdminVoice = (voiceId: string) => {
  const invalidate = useInvalidateCatalog();
  return useMutation({
    mutationFn: (input: AdminVoiceUpdateInput) => updateAdminVoice(voiceId, input),
    onSuccess: invalidate,
  });
};

export const useRegenerateVoicePreview = (voiceId: string) => {
  const invalidate = useInvalidateCatalog();
  return useMutation({
    mutationFn: () => regenerateVoicePreview(voiceId),
    onSuccess: invalidate,
  });
};
