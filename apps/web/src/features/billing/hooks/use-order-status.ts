"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { getOrder } from "@/features/billing/api/billing.api";
import { billingKeys } from "@/features/billing/query-keys";
import type { OrderStatus } from "@/features/billing/types/billing.types";
import { creditsKeys } from "@/features/credits/query-keys";
import { ApiError } from "@/lib/api/api-error";

export const ORDER_POLL_INITIAL_MS = 1_000;
export const ORDER_POLL_MAX_MS = 8_000;
export const ORDER_POLL_BUDGET_MS = 120_000;

export const buildPollSchedule = (
  initialMs: number = ORDER_POLL_INITIAL_MS,
  maxMs: number = ORDER_POLL_MAX_MS,
  budgetMs: number = ORDER_POLL_BUDGET_MS,
): number[] => {
  const delays: number[] = [];
  let elapsed = 0;
  while (elapsed < budgetMs) {
    const delay = Math.min(initialMs * 2 ** delays.length, maxMs);
    delays.push(delay);
    elapsed += delay;
  }
  return delays;
};

export const ORDER_POLL_SCHEDULE = buildPollSchedule();

const SETTLED_STATUSES: ReadonlySet<OrderStatus> = new Set([
  "paid",
  "failed",
  "expired",
  "cancelled",
]);

export const isOrderSettled = (status: OrderStatus): boolean => SETTLED_STATUSES.has(status);

export const useOrderStatus = (orderId: string) => {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: billingKeys.order(orderId),
    queryFn: () => getOrder(orderId),
    staleTime: 0,
    refetchOnMount: "always",
    notifyOnChangeProps: "all",
    refetchInterval: (current) => {
      if (current.state.data && isOrderSettled(current.state.data.status)) {
        return false;
      }
      if (current.state.error && !ApiError.from(current.state.error).isTransient) {
        return false;
      }
      const fetches = current.state.dataUpdateCount + current.state.errorUpdateCount;
      return ORDER_POLL_SCHEDULE[fetches - 1] ?? false;
    },
  });
  const status = query.data?.status;
  const paid = status === "paid";

  useEffect(() => {
    if (!paid) {
      return;
    }
    void Promise.all([
      client.invalidateQueries({ queryKey: creditsKeys.wallet() }),
      client.invalidateQueries({ queryKey: creditsKeys.ledger() }),
      client.invalidateQueries({ queryKey: billingKeys.history() }),
      client.invalidateQueries({ queryKey: billingKeys.subscription() }),
    ]);
  }, [paid, client]);

  const settled = status !== undefined && isOrderSettled(status);
  const state = client.getQueryState(billingKeys.order(orderId));
  const fetches = (state?.dataUpdateCount ?? 0) + (state?.errorUpdateCount ?? 0);
  const exhausted = !settled && query.data !== undefined && fetches > ORDER_POLL_SCHEDULE.length;

  const restart = () => client.resetQueries({ queryKey: billingKeys.order(orderId) });

  return { query, exhausted, restart };
};
