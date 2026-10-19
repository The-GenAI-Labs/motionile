"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  cancelSubscription,
  getSubscription,
  listSubscriptions,
} from "@/features/admin-billing/api/admin-billing.api";
import { adminBillingKeys } from "@/features/admin-billing/query-keys";
import type { SubscriptionFilters } from "@/features/admin-billing/types/admin-billing.types";
import { useCursorList } from "@/lib/query/use-cursor-list";

export const useAdminSubscriptions = (filters: SubscriptionFilters) =>
  useCursorList(adminBillingKeys.subscriptionList(filters), (cursor) =>
    listSubscriptions(filters, cursor),
  );

export const useAdminSubscription = (subscriptionId: string) =>
  useQuery({
    queryKey: adminBillingKeys.subscription(subscriptionId),
    queryFn: () => getSubscription(subscriptionId),
  });

export const useCancelSubscription = (subscriptionId: string) => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (immediately: boolean) => cancelSubscription(subscriptionId, immediately),
    onSuccess: (subscription) => {
      client.setQueryData(adminBillingKeys.subscription(subscriptionId), subscription);
      return client.invalidateQueries({ queryKey: adminBillingKeys.subscriptions() });
    },
  });
};
