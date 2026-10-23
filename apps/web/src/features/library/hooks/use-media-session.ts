"use client";

import { type Query, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  MIN_REFRESH_DELAY_MS,
  refreshAtMs,
  syncMediaSession,
} from "@/features/library/media-session-sync";
import { libraryKeys } from "@/features/library/query-keys";
import type { MediaSession } from "@/features/library/types/library.types";
import { DEFAULT_STALE_TIME_MS } from "@/lib/query/query-client";

type SessionQuery = Query<MediaSession, Error, MediaSession>;

let forcedRefresh: Promise<MediaSession> | undefined;

const freshForMs = (query: SessionQuery): number => {
  const at = refreshAtMs(query.state.data);
  if (at === null) {
    return query.state.data === undefined ? 0 : Number.POSITIVE_INFINITY;
  }
  return Math.max(0, at - query.state.dataUpdatedAt);
};

const nextRefreshDelayMs = (query: SessionQuery): number | false => {
  const at = refreshAtMs(query.state.data);
  return at === null ? false : Math.max(MIN_REFRESH_DELAY_MS, at - Date.now());
};

interface UseMediaSessionOptions {
  enabled?: boolean;
}

export const useMediaSession = ({ enabled = true }: UseMediaSessionOptions = {}) => {
  const client = useQueryClient();
  const query = useQuery<MediaSession, Error, MediaSession>({
    queryKey: libraryKeys.mediaSession(),
    queryFn: ({ client: queryClient, queryKey }) =>
      syncMediaSession(queryClient.getQueryData(queryKey) !== undefined),
    enabled,
    staleTime: freshForMs,
    gcTime: DEFAULT_STALE_TIME_MS * 5,
    refetchInterval: nextRefreshDelayMs,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
  });

  const refresh = async (): Promise<void> => {
    forcedRefresh ??= syncMediaSession(false).finally(() => {
      forcedRefresh = undefined;
    });
    client.setQueryData(libraryKeys.mediaSession(), await forcedRefresh);
  };

  return {
    mode: query.data?.mode,
    expiresAt: query.data?.expiresAt ?? null,
    isReady: query.isSuccess,
    isPending: query.isPending,
    isError: query.isError,
    error: query.error,
    refresh,
  };
};
