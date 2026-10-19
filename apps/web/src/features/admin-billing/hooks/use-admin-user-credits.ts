"use client";

import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import {
  adjustUserCredits,
  getUserCredits,
  listUserCreditLedger,
} from "@/features/admin-billing/api/admin-billing.api";
import { adminBillingKeys } from "@/features/admin-billing/query-keys";
import { getNextPageParam } from "@/lib/api/pagination";
import { useCursorList } from "@/lib/query/use-cursor-list";

export const useAdminUserCredits = (userId: string) =>
  useInfiniteQuery({
    queryKey: adminBillingKeys.userCredits(userId),
    queryFn: ({ pageParam }) => getUserCredits(userId, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (page) => getNextPageParam({ items: page.lots, nextCursor: page.nextCursor }),
  });

export const useAdminUserLedger = (userId: string) =>
  useCursorList(adminBillingKeys.userLedger(userId), (cursor) =>
    listUserCreditLedger(userId, cursor),
  );

export const useAdjustCredits = (userId: string) => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      request: Parameters<typeof adjustUserCredits>[1];
      idempotencyKey: string;
    }) => adjustUserCredits(userId, input.request, input.idempotencyKey),
    onSuccess: () => client.invalidateQueries({ queryKey: adminBillingKeys.credits() }),
  });
};
