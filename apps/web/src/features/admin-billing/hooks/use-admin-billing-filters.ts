"use client";

import {
  zOrderStatusName,
  zPaymentStatusName,
  zProductKindName,
  zRefundStatusName,
  zRunStatusName,
  zRunTypeName,
  zSubscriptionStatusName,
  zWebhookStatusName,
} from "@motionile/api-contract";
import { parseAsBoolean, parseAsString, parseAsStringLiteral, useQueryStates } from "nuqs";
import { z } from "zod";

import { endOfDay, startOfDay } from "@/features/admin-billing/api/admin-billing.api";
import type {
  OrderFilters,
  PaymentFilters,
  ProductFilters,
  RefundFilters,
  RunFilters,
  SubscriptionFilters,
  WebhookFilters,
} from "@/features/admin-billing/types/admin-billing.types";

const text = parseAsString.withDefault("");

const isDate = (value: string): boolean => z.iso.date().safeParse(value).success;

const isUuid = (value: string): boolean => z.uuid().safeParse(value).success;

export const productFilterParsers = {
  q: text,
  kind: parseAsStringLiteral(zProductKindName.options),
  active: parseAsBoolean,
  sample: parseAsBoolean,
};

export const paymentFilterParsers = {
  status: parseAsStringLiteral(zPaymentStatusName.options),
  flagged: parseAsBoolean,
  user: text,
  order: text,
  from: text,
  to: text,
};

export const orderFilterParsers = {
  status: parseAsStringLiteral(zOrderStatusName.options),
  flagged: parseAsBoolean,
  user: text,
};

export const refundFilterParsers = {
  status: parseAsStringLiteral(zRefundStatusName.options),
  payment: text,
};

export const subscriptionFilterParsers = {
  status: parseAsStringLiteral(zSubscriptionStatusName.options),
  plan: text,
  user: text,
};

export const webhookFilterParsers = {
  status: parseAsStringLiteral(zWebhookStatusName.options),
  type: text,
  from: text,
  to: text,
};

export const runFilterParsers = {
  type: parseAsStringLiteral(zRunTypeName.options),
  status: parseAsStringLiteral(zRunStatusName.options),
  mismatches: parseAsBoolean,
};

const options = { history: "replace" } as const;

export const useProductFilterState = () => useQueryStates(productFilterParsers, options);
export const usePaymentFilterState = () => useQueryStates(paymentFilterParsers, options);
export const useOrderFilterState = () => useQueryStates(orderFilterParsers, options);
export const useRefundFilterState = () => useQueryStates(refundFilterParsers, options);
export const useSubscriptionFilterState = () => useQueryStates(subscriptionFilterParsers, options);
export const useWebhookFilterState = () => useQueryStates(webhookFilterParsers, options);
export const useRunFilterState = () => useQueryStates(runFilterParsers, options);

type ProductState = ReturnType<typeof useProductFilterState>[0];
type PaymentState = ReturnType<typeof usePaymentFilterState>[0];
type OrderState = ReturnType<typeof useOrderFilterState>[0];
type RefundState = ReturnType<typeof useRefundFilterState>[0];
type SubscriptionState = ReturnType<typeof useSubscriptionFilterState>[0];
type WebhookState = ReturnType<typeof useWebhookFilterState>[0];
type RunState = ReturnType<typeof useRunFilterState>[0];

export const toProductFilters = (state: ProductState, search: string): ProductFilters => ({
  ...(state.kind === null ? {} : { kind: state.kind }),
  ...(state.active === null ? {} : { isActive: state.active }),
  ...(state.sample === null ? {} : { isSample: state.sample }),
  ...(search.trim() === "" ? {} : { search: search.trim() }),
});

export const toPaymentFilters = (state: PaymentState): PaymentFilters => ({
  ...(state.status === null ? {} : { status: state.status }),
  ...(state.flagged === null ? {} : { flagged: state.flagged }),
  ...(isUuid(state.user) ? { userId: state.user } : {}),
  ...(isUuid(state.order) ? { orderId: state.order } : {}),
  ...(isDate(state.from) ? { createdFrom: startOfDay(state.from) } : {}),
  ...(isDate(state.to) ? { createdTo: endOfDay(state.to) } : {}),
});

export const toOrderFilters = (state: OrderState): OrderFilters => ({
  ...(state.status === null ? {} : { status: state.status }),
  ...(state.flagged === null ? {} : { flagged: state.flagged }),
  ...(isUuid(state.user) ? { userId: state.user } : {}),
});

export const toRefundFilters = (state: RefundState): RefundFilters => ({
  ...(state.status === null ? {} : { status: state.status }),
  ...(isUuid(state.payment) ? { paymentId: state.payment } : {}),
});

export const toSubscriptionFilters = (state: SubscriptionState): SubscriptionFilters => ({
  ...(state.status === null ? {} : { status: state.status }),
  ...(state.plan === "" ? {} : { planKey: state.plan }),
  ...(isUuid(state.user) ? { userId: state.user } : {}),
});

export const toWebhookFilters = (state: WebhookState): WebhookFilters => ({
  ...(state.status === null ? {} : { status: state.status }),
  ...(state.type === "" ? {} : { eventType: state.type }),
  ...(isDate(state.from) ? { receivedFrom: startOfDay(state.from) } : {}),
  ...(isDate(state.to) ? { receivedTo: endOfDay(state.to) } : {}),
});

export const toRunFilters = (state: RunState): RunFilters => ({
  ...(state.type === null ? {} : { type: state.type }),
  ...(state.status === null ? {} : { status: state.status }),
  ...(state.mismatches === null ? {} : { hasMismatches: state.mismatches }),
});
