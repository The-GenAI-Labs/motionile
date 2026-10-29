"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createShareLink,
  deleteJob,
  listJobs,
  revokeShareLinks,
} from "@/features/generation/api/generation.api";
import { listLibrary } from "@/features/library/api/library.api";
import { libraryKeys } from "@/features/library/query-keys";
import { isActiveJob, RECENT_VIDEOS_LIMIT } from "@/features/library/schemas/library.schema";
import type { LibraryFilters, ShareInput } from "@/features/library/types/library.types";
import { useCursorList } from "@/lib/query/use-cursor-list";

const ACTIVE_JOBS_POLL_MS = 5_000;

export const useLibrary = (filters: LibraryFilters) =>
  useCursorList(libraryKeys.list(filters), (cursor) => listLibrary(filters, cursor));

export const useRecentVideos = () =>
  useQuery({
    queryKey: libraryKeys.recent(),
    queryFn: () => listLibrary({}, undefined, RECENT_VIDEOS_LIMIT),
    select: (page) => page.items,
  });

export const useActiveJobs = () =>
  useQuery({
    queryKey: libraryKeys.activeJobs(),
    queryFn: () => listJobs({}),
    select: (page) => page.items.filter(isActiveJob),
    refetchInterval: (query) =>
      query.state.data?.items.some(isActiveJob) ? ACTIVE_JOBS_POLL_MS : false,
  });

const useRefreshLibrary = () => {
  const client = useQueryClient();
  return () =>
    Promise.all([
      client.invalidateQueries({ queryKey: libraryKeys.lists() }),
      client.invalidateQueries({ queryKey: libraryKeys.recent() }),
      client.invalidateQueries({ queryKey: libraryKeys.activeJobs() }),
    ]);
};

export const useDeleteVideo = () => {
  const refresh = useRefreshLibrary();
  return useMutation({ mutationFn: (jobId: string) => deleteJob(jobId), onSuccess: refresh });
};

export const useCreateShareLink = (jobId: string) => {
  const refresh = useRefreshLibrary();
  return useMutation({
    mutationFn: (input: ShareInput) => createShareLink(jobId, input),
    onSuccess: refresh,
  });
};

export const useRevokeShareLinks = (jobId: string) => {
  const refresh = useRefreshLibrary();
  return useMutation({ mutationFn: () => revokeShareLinks(jobId), onSuccess: refresh });
};
