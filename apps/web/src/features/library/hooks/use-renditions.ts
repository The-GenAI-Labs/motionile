"use client";

import { type Query, useQuery } from "@tanstack/react-query";

import { listRenditions } from "@/features/library/api/library.api";
import { libraryKeys } from "@/features/library/query-keys";
import type { Rendition } from "@/features/library/types/library.types";
import { earliestExpiryMs } from "@/features/library/url-expiry";
import { DEFAULT_STALE_TIME_MS } from "@/lib/query/query-client";

export const RENDITION_REFRESH_LEAD_MS = 60_000;
export const MIN_RENDITION_REFRESH_DELAY_MS = 10_000;

type RenditionList = Awaited<ReturnType<typeof listRenditions>>;
type RenditionQuery = Query<RenditionList, Error, RenditionList>;

const refreshAtMs = (query: RenditionQuery): number | null => {
  const expiry = earliestExpiryMs(query.state.data?.items ?? []);
  return expiry === null ? null : expiry - RENDITION_REFRESH_LEAD_MS;
};

const freshForMs = (query: RenditionQuery): number => {
  const at = refreshAtMs(query);
  return at === null ? DEFAULT_STALE_TIME_MS : Math.max(0, at - query.state.dataUpdatedAt);
};

const nextRefreshDelayMs = (query: RenditionQuery): number | false => {
  const at = refreshAtMs(query);
  return at === null ? false : Math.max(MIN_RENDITION_REFRESH_DELAY_MS, at - Date.now());
};

interface UseRenditionsOptions {
  enabled?: boolean;
}

export const useRenditions = (renderId: string, { enabled = true }: UseRenditionsOptions = {}) =>
  useQuery<RenditionList, Error, Rendition[]>({
    queryKey: libraryKeys.renditions(renderId),
    queryFn: () => listRenditions(renderId),
    select: (list) => list.items,
    enabled,
    staleTime: freshForMs,
    refetchInterval: nextRefreshDelayMs,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
  });
