import {
  defaultShouldDehydrateQuery,
  environmentManager,
  type Query,
  QueryClient,
} from "@tanstack/react-query";

import { ApiError } from "@/lib/api/api-error";

export const MAX_QUERY_RETRIES = 2;
export const DEFAULT_STALE_TIME_MS = 60_000;
export const BASE_RETRY_DELAY_MS = 1_000;
export const MAX_RETRY_DELAY_MS = 10_000;

export const shouldRetryQuery = (failureCount: number, error: unknown): boolean =>
  failureCount < MAX_QUERY_RETRIES && ApiError.from(error).isTransient;

export const retryDelay = (attemptIndex: number, error?: unknown): number => {
  const backoff = Math.min(BASE_RETRY_DELAY_MS * 2 ** attemptIndex, MAX_RETRY_DELAY_MS);
  const retryAfterSeconds = error === undefined ? null : ApiError.from(error).retryAfterSeconds;
  if (retryAfterSeconds === null) {
    return backoff;
  }
  return Math.min(Math.max(backoff, retryAfterSeconds * 1_000), MAX_RETRY_DELAY_MS);
};

export const shouldDehydrateQuery = (query: Query): boolean =>
  defaultShouldDehydrateQuery(query) || query.state.status === "pending";

export const makeQueryClient = (): QueryClient =>
  new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: DEFAULT_STALE_TIME_MS,
        refetchOnWindowFocus: false,
        retry: shouldRetryQuery,
        retryDelay,
      },
      mutations: {
        retry: false,
      },
      dehydrate: {
        shouldDehydrateQuery,
      },
    },
  });

let browserQueryClient: QueryClient | undefined;

export const getQueryClient = (): QueryClient => {
  if (environmentManager.isServer()) {
    return makeQueryClient();
  }
  browserQueryClient ??= makeQueryClient();
  return browserQueryClient;
};
