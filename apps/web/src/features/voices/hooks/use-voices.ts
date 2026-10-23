"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { userKeys } from "@/features/users/query-keys";
import {
  deleteVoice,
  getVoice,
  getVoicePreview,
  listVoices,
} from "@/features/voices/api/voices.api";
import { voiceKeys } from "@/features/voices/query-keys";
import type { Voice, VoiceFilters } from "@/features/voices/types/voices.types";
import { flattenCursorPages, getNextPageParam } from "@/lib/api/pagination";

export const VOICE_POLL_INTERVAL_MS = 4_000;
export const PREVIEW_STALE_MS = 60_000;

const hasPending = (voices: readonly Voice[]): boolean =>
  voices.some((voice) => voice.status === "pending");

export const useAllVoices = (filters: VoiceFilters) => {
  const query = useInfiniteQuery({
    queryKey: voiceKeys.list(filters),
    queryFn: ({ pageParam }) => listVoices(filters, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam,
    refetchInterval: (current) =>
      hasPending(flattenCursorPages(current.state.data?.pages)) ? VOICE_POLL_INTERVAL_MS : false,
  });
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = query;
  useEffect(() => {
    if (hasNextPage && !isFetchingNextPage) {
      void fetchNextPage();
    }
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);
  return {
    voices: flattenCursorPages(query.data?.pages),
    isPending: query.isPending,
    isLoadingAll: query.isFetchingNextPage || query.hasNextPage,
    isError: query.isError,
    error: query.error,
    refetch: query.refetch,
  };
};

export const useVoice = (voiceId: string | null) =>
  useQuery({
    queryKey: voiceKeys.detail(voiceId ?? "none"),
    queryFn: () => getVoice(voiceId ?? ""),
    enabled: voiceId !== null,
    refetchInterval: (current) =>
      current.state.data?.status === "pending" ? VOICE_POLL_INTERVAL_MS : false,
  });

export const useVoicePreviewLoader = () => {
  const client = useQueryClient();
  return (voiceId: string) =>
    client.query({
      queryKey: voiceKeys.preview(voiceId),
      queryFn: () => getVoicePreview(voiceId),
      staleTime: PREVIEW_STALE_MS,
    });
};

export const useDeleteVoice = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (voiceId: string) => deleteVoice(voiceId),
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: voiceKeys.lists() }),
        client.invalidateQueries({ queryKey: userKeys.preferences() }),
      ]),
  });
};
