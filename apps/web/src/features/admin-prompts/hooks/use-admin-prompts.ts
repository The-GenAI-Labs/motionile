"use client";

import {
  skipToken,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import {
  activatePromptVersion,
  createPromptDraft,
  diffPromptVersions,
  listEvalRuns,
  listPromptTemplates,
  listPromptVersions,
  rollbackPromptTemplate,
  startEvalRun,
} from "@/features/admin-prompts/api/admin-prompts.api";
import { adminPromptsKeys } from "@/features/admin-prompts/query-keys";
import type {
  DiffRequest,
  DraftInput,
  EvalRunFilters,
  StartEvalRunInput,
} from "@/features/admin-prompts/types/admin-prompts.types";
import { getNextPageParam } from "@/lib/api/pagination";
import { useCursorList } from "@/lib/query/use-cursor-list";

const RUNNING_POLL_MS = 5_000;

export const usePromptTemplates = () =>
  useQuery({ queryKey: adminPromptsKeys.templates(), queryFn: listPromptTemplates });

export const usePromptVersions = (key: string) =>
  useCursorList(adminPromptsKeys.versions(key), (cursor) => listPromptVersions(key, cursor));

export const usePromptDiff = (request: DiffRequest | null) =>
  useQuery({
    queryKey: adminPromptsKeys.diff(request),
    queryFn: request === null ? skipToken : () => diffPromptVersions(request),
    staleTime: 0,
    gcTime: 0,
  });

export const useEvalRuns = (filters: EvalRunFilters) =>
  useInfiniteQuery({
    queryKey: adminPromptsKeys.evalRunList(filters),
    queryFn: ({ pageParam }) => listEvalRuns(filters, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam,
    refetchInterval: (query) =>
      query.state.data?.pages.some((page) => page.items.some((run) => run.status === "running"))
        ? RUNNING_POLL_MS
        : false,
  });

const useRefreshPrompts = () => {
  const client = useQueryClient();
  return (key: string) =>
    Promise.all([
      client.invalidateQueries({ queryKey: adminPromptsKeys.templates() }),
      client.invalidateQueries({ queryKey: adminPromptsKeys.versions(key) }),
    ]);
};

export const useCreatePromptDraft = (key: string) => {
  const refresh = useRefreshPrompts();
  return useMutation({
    mutationFn: (input: DraftInput) => createPromptDraft(key, input),
    onSuccess: () => refresh(key),
  });
};

export const useActivatePromptVersion = (key: string) => {
  const refresh = useRefreshPrompts();
  return useMutation({
    mutationFn: (version: number) => activatePromptVersion(key, version),
    onSuccess: () => refresh(key),
  });
};

export const useRollbackPromptTemplate = (key: string) => {
  const refresh = useRefreshPrompts();
  return useMutation({
    mutationFn: () => rollbackPromptTemplate(key),
    onSuccess: () => refresh(key),
  });
};

export const useStartEvalRun = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: StartEvalRunInput) => startEvalRun(input),
    onSuccess: () => client.invalidateQueries({ queryKey: adminPromptsKeys.evalRuns() }),
  });
};
