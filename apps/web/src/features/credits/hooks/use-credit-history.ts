"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { listDailyUsage, listLedger, listUsage } from "@/features/credits/api/credits.api";
import { creditsKeys } from "@/features/credits/query-keys";
import { getNextPageParam } from "@/lib/api/pagination";

export const useLedger = () =>
  useInfiniteQuery({
    queryKey: creditsKeys.ledger(),
    queryFn: ({ pageParam }) => listLedger(pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam,
  });

export const useUsageEntries = () =>
  useInfiniteQuery({
    queryKey: creditsKeys.usage("entries"),
    queryFn: ({ pageParam }) => listUsage(pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam,
  });

export const useDailyUsage = () =>
  useQuery({ queryKey: creditsKeys.usage("daily"), queryFn: listDailyUsage });
