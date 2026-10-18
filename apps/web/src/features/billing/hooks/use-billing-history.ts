"use client";

import { useInfiniteQuery } from "@tanstack/react-query";

import { listHistory } from "@/features/billing/api/billing.api";
import { billingKeys } from "@/features/billing/query-keys";
import { getNextPageParam } from "@/lib/api/pagination";

export const useBillingHistory = () =>
  useInfiniteQuery({
    queryKey: billingKeys.history(),
    queryFn: ({ pageParam }) => listHistory(pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam,
  });
