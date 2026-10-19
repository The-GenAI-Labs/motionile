"use client";

import { useQuery } from "@tanstack/react-query";

import {
  creditsAnalytics,
  revenueAnalytics,
  subscriptionAnalytics,
} from "@/features/admin-billing/api/admin-billing.api";
import { adminBillingKeys } from "@/features/admin-billing/query-keys";
import type { DateRange } from "@/features/admin-billing/types/admin-billing.types";

export const useRevenueAnalytics = (range: DateRange) =>
  useQuery({
    queryKey: adminBillingKeys.revenue(range),
    queryFn: () => revenueAnalytics(range),
  });

export const useCreditsAnalytics = (range: DateRange) =>
  useQuery({
    queryKey: adminBillingKeys.creditsAnalytics(range),
    queryFn: () => creditsAnalytics(range),
  });

export const useSubscriptionAnalytics = () =>
  useQuery({
    queryKey: adminBillingKeys.subscriptionAnalytics(),
    queryFn: subscriptionAnalytics,
  });
