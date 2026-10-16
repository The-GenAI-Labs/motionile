"use client";
import { useInfiniteQuery } from "@tanstack/react-query";

import { sessions } from "@/features/auth/api/auth.api";
import { authKeys } from "@/features/auth/query-keys";
export const useSessions = () =>
  useInfiniteQuery({
    queryKey: authKeys.sessions(),
    queryFn: ({ pageParam }) => sessions(pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (page) => page.nextCursor ?? undefined,
  });
