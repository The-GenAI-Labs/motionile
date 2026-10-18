"use client";

import { type QueryKey, useInfiniteQuery } from "@tanstack/react-query";

import { type CursorPage, getNextPageParam } from "@/lib/api/pagination";

export const useCursorList = <Item>(
  queryKey: QueryKey,
  fetchPage: (cursor: string | undefined) => Promise<CursorPage<Item>>,
) =>
  useInfiniteQuery({
    queryKey,
    queryFn: ({ pageParam }) => fetchPage(pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam,
  });
