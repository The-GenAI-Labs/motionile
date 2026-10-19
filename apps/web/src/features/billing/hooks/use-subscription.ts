"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  cancelSubscription,
  changeSubscription,
  getSubscription,
} from "@/features/billing/api/billing.api";
import { billingKeys } from "@/features/billing/query-keys";
import { creditsKeys } from "@/features/credits/query-keys";

export const useSubscription = (options: { enabled?: boolean } = {}) =>
  useQuery({
    queryKey: billingKeys.subscription(),
    queryFn: getSubscription,
    enabled: options.enabled ?? true,
  });

export const useCancelSubscription = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => cancelSubscription(),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: billingKeys.subscription() }),
        client.invalidateQueries({ queryKey: billingKeys.history() }),
      ]);
    },
  });
};

export const useChangeSubscription = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (productCode: string) => changeSubscription(productCode),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: billingKeys.subscription() }),
        client.invalidateQueries({ queryKey: creditsKeys.wallet() }),
      ]);
    },
  });
};
