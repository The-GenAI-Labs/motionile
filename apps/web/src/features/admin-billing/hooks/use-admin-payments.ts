"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createRefund,
  getOrder,
  getPayment,
  getRefund,
  listOrders,
  listPayments,
  listRefunds,
} from "@/features/admin-billing/api/admin-billing.api";
import { adminBillingKeys } from "@/features/admin-billing/query-keys";
import type {
  OrderFilters,
  PaymentFilters,
  RefundFilters,
} from "@/features/admin-billing/types/admin-billing.types";
import { useCursorList } from "@/lib/query/use-cursor-list";

export const useAdminPayments = (filters: PaymentFilters) =>
  useCursorList(adminBillingKeys.paymentList(filters), (cursor) => listPayments(filters, cursor));

export const useAdminPayment = (paymentId: string) =>
  useQuery({
    queryKey: adminBillingKeys.payment(paymentId),
    queryFn: () => getPayment(paymentId),
  });

export const useClawbackPreview = (paymentId: string, amountPaise: number | undefined) =>
  useQuery({
    queryKey: adminBillingKeys.payment(paymentId, amountPaise),
    queryFn: () => getPayment(paymentId, amountPaise),
    enabled: amountPaise !== undefined,
    placeholderData: keepPreviousData,
  });

export const useCreateRefund = (paymentId: string) => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { request: Parameters<typeof createRefund>[1]; idempotencyKey: string }) =>
      createRefund(paymentId, input.request, input.idempotencyKey),
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: adminBillingKeys.payments() }),
        client.invalidateQueries({ queryKey: adminBillingKeys.refunds() }),
        client.invalidateQueries({ queryKey: adminBillingKeys.credits() }),
      ]),
  });
};

export const useAdminOrders = (filters: OrderFilters) =>
  useCursorList(adminBillingKeys.orderList(filters), (cursor) => listOrders(filters, cursor));

export const useAdminOrder = (orderId: string) =>
  useQuery({ queryKey: adminBillingKeys.order(orderId), queryFn: () => getOrder(orderId) });

export const useAdminRefunds = (filters: RefundFilters) =>
  useCursorList(adminBillingKeys.refundList(filters), (cursor) => listRefunds(filters, cursor));

export const useAdminRefund = (refundId: string) =>
  useQuery({ queryKey: adminBillingKeys.refund(refundId), queryFn: () => getRefund(refundId) });
