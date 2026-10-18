"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getWebhookEvent,
  listWebhookEvents,
  reprocessWebhookEvent,
} from "@/features/admin-billing/api/admin-billing.api";
import { adminBillingKeys } from "@/features/admin-billing/query-keys";
import type { WebhookFilters } from "@/features/admin-billing/types/admin-billing.types";
import { useCursorList } from "@/lib/query/use-cursor-list";

export const useAdminWebhooks = (filters: WebhookFilters) =>
  useCursorList(adminBillingKeys.webhookList(filters), (cursor) =>
    listWebhookEvents(filters, cursor),
  );

export const useAdminWebhook = (eventId: string) =>
  useQuery({
    queryKey: adminBillingKeys.webhook(eventId),
    queryFn: () => getWebhookEvent(eventId),
  });

export const useReprocessWebhook = (eventId: string) => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => reprocessWebhookEvent(eventId),
    onSuccess: () => client.invalidateQueries({ queryKey: adminBillingKeys.webhooks() }),
  });
};
