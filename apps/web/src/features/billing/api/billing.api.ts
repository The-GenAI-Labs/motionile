import * as contract from "@motionile/api-contract";
import type { z } from "zod";

import { idempotencyKeySchema, orderIdSchema } from "@/features/billing/schemas/billing.schema";
import { apiClient } from "@/lib/api/client";

export const IDEMPOTENCY_HEADER = "Idempotency-Key";

export const HISTORY_PAGE_SIZE = 20;

const idempotencyHeaders = (key: string) => ({
  [IDEMPOTENCY_HEADER]: idempotencyKeySchema.parse(key),
});

export const listProducts = async () =>
  contract.zBillingListProductsResponse.parse(
    (await apiClient.get<unknown>("/v1/billing/products")).data,
  );

export const createOrder = async (input: { productCode: string; idempotencyKey: string }) =>
  contract.zBillingCreateOrderResponse.parse(
    (
      await apiClient.post<unknown>(
        "/v1/billing/orders",
        contract.zBillingCreateOrderBody.parse({ productCode: input.productCode }),
        { authenticated: true, headers: idempotencyHeaders(input.idempotencyKey) },
      )
    ).data,
  );

export const getOrder = async (orderId: string) =>
  contract.zBillingGetOrderResponse.parse(
    (
      await apiClient.get<unknown>(`/v1/billing/orders/${orderIdSchema.parse(orderId)}`, {
        authenticated: true,
      })
    ).data,
  );

export const verifyPayment = async (input: z.input<typeof contract.zBillingVerifyPaymentBody>) => {
  const body = contract.zBillingVerifyPaymentBody.parse(input);
  return contract.zBillingVerifyPaymentResponse.parse(
    (
      await apiClient.post<unknown>("/v1/billing/payments/verify", body, {
        authenticated: true,
        headers: idempotencyHeaders(`verify:${body.razorpayPaymentId}`),
      })
    ).data,
  );
};

export const listHistory = async (cursor?: string) =>
  contract.zBillingListHistoryResponse.parse(
    (
      await apiClient.get<unknown>("/v1/billing/history", {
        authenticated: true,
        params: contract.zBillingListHistoryQuery.parse({ cursor, limit: HISTORY_PAGE_SIZE }),
      })
    ).data,
  );

export const createSubscription = async (input: { productCode: string; idempotencyKey: string }) =>
  contract.zBillingCreateSubscriptionResponse.parse(
    (
      await apiClient.post<unknown>(
        "/v1/billing/subscriptions",
        contract.zBillingCreateSubscriptionBody.parse({ productCode: input.productCode }),
        { authenticated: true, headers: idempotencyHeaders(input.idempotencyKey) },
      )
    ).data,
  );

export const verifySubscription = async (
  input: z.input<typeof contract.zBillingVerifySubscriptionBody>,
) => {
  const body = contract.zBillingVerifySubscriptionBody.parse(input);
  return contract.zBillingVerifySubscriptionResponse.parse(
    (
      await apiClient.post<unknown>("/v1/billing/subscriptions/verify", body, {
        authenticated: true,
        headers: idempotencyHeaders(`verify:${body.razorpayPaymentId}`),
      })
    ).data,
  );
};

export const getSubscription = async () =>
  contract.zBillingGetSubscriptionResponse.parse(
    (await apiClient.get<unknown>("/v1/billing/subscription", { authenticated: true })).data,
  );

export const cancelSubscription = async () =>
  contract.zBillingCancelSubscriptionResponse.parse(
    (
      await apiClient.post<unknown>("/v1/billing/subscription/cancel", undefined, {
        authenticated: true,
      })
    ).data,
  );

export const changeSubscription = async (productCode: string) =>
  contract.zBillingChangeSubscriptionResponse.parse(
    (
      await apiClient.post<unknown>(
        "/v1/billing/subscription/change",
        contract.zBillingChangeSubscriptionBody.parse({ productCode }),
        { authenticated: true },
      )
    ).data,
  );
