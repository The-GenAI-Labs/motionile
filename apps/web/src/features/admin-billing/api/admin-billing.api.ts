import * as contract from "@motionile/api-contract";
import { z } from "zod";

import type {
  DateRange,
  OrderFilters,
  PaymentFilters,
  ProductFilters,
  RefundFilters,
  RunFilters,
  SubscriptionFilters,
  WebhookFilters,
} from "@/features/admin-billing/types/admin-billing.types";
import { IDEMPOTENCY_HEADER } from "@/features/billing/api/billing.api";
import { idempotencyKeySchema } from "@/features/billing/schemas/billing.schema";
import { apiClient } from "@/lib/api/client";

export const ADMIN_PAGE_SIZE = 25;

const BASE = "/v1/admin/billing";

const pathId = (value: string): string => z.uuid().parse(value);

const get = async <Schema extends z.ZodType>(
  path: string,
  schema: Schema,
  params?: Record<string, unknown>,
): Promise<z.output<Schema>> =>
  schema.parse(
    (await apiClient.get<unknown>(`${BASE}${path}`, { authenticated: true, params })).data,
  );

const send = async <Schema extends z.ZodType>(
  method: "post" | "patch",
  path: string,
  schema: Schema,
  body?: unknown,
  headers?: Record<string, string>,
): Promise<z.output<Schema>> =>
  schema.parse(
    (
      await apiClient.request<unknown>({
        method,
        url: `${BASE}${path}`,
        data: body,
        authenticated: true,
        ...(headers ? { headers } : {}),
      })
    ).data,
  );

const idempotencyHeaders = (key: string): Record<string, string> => ({
  [IDEMPOTENCY_HEADER]: idempotencyKeySchema.parse(key),
});

export const startOfDay = (date: string): string => `${date}T00:00:00.000Z`;

export const endOfDay = (date: string): string => `${date}T23:59:59.999Z`;

export const revenueAnalytics = (range: DateRange) =>
  get(
    "/analytics/revenue",
    contract.zAdminBillingGetRevenueAnalyticsResponse,
    contract.zAdminBillingGetRevenueAnalyticsQuery.parse(range),
  );

export const creditsAnalytics = (range: DateRange) =>
  get(
    "/analytics/credits",
    contract.zAdminBillingGetCreditsAnalyticsResponse,
    contract.zAdminBillingGetCreditsAnalyticsQuery.parse(range),
  );

export const subscriptionAnalytics = () =>
  get("/analytics/subscriptions", contract.zAdminBillingGetSubscriptionAnalyticsResponse);

export const listProducts = (filters: ProductFilters, cursor?: string) =>
  get(
    "/products",
    contract.zAdminBillingListProductsResponse,
    contract.zAdminBillingListProductsQuery.parse({ ...filters, cursor, limit: ADMIN_PAGE_SIZE }),
  );

export const getProduct = (productId: string) =>
  get(`/products/${pathId(productId)}`, contract.zAdminBillingGetProductResponse);

export const createProduct = (input: z.input<typeof contract.zAdminBillingCreateProductBody>) =>
  send(
    "post",
    "/products",
    contract.zAdminBillingCreateProductResponse,
    contract.zAdminBillingCreateProductBody.parse(input),
  );

export const updateProduct = (
  productId: string,
  input: z.input<typeof contract.zAdminBillingUpdateProductBody>,
) =>
  send(
    "patch",
    `/products/${pathId(productId)}`,
    contract.zAdminBillingUpdateProductResponse,
    contract.zAdminBillingUpdateProductBody.parse(input),
  );

export const duplicateProduct = (
  productId: string,
  overrides: z.input<typeof contract.zDuplicateProductRequest>,
) =>
  send(
    "post",
    `/products/${pathId(productId)}/duplicate`,
    contract.zAdminBillingDuplicateProductResponse,
    contract.zAdminBillingDuplicateProductBody.parse(overrides),
  );

export const activateProduct = (productId: string) =>
  send(
    "post",
    `/products/${pathId(productId)}/activate`,
    contract.zAdminBillingActivateProductResponse,
  );

export const deactivateProduct = (productId: string) =>
  send(
    "post",
    `/products/${pathId(productId)}/deactivate`,
    contract.zAdminBillingDeactivateProductResponse,
  );

export const syncProductPlan = (productId: string) =>
  send(
    "post",
    `/products/${pathId(productId)}/sync-plan`,
    contract.zAdminBillingSyncProductPlanResponse,
  );

export const listPayments = (filters: PaymentFilters, cursor?: string) =>
  get(
    "/payments",
    contract.zAdminBillingListPaymentsResponse,
    contract.zAdminBillingListPaymentsQuery.parse({ ...filters, cursor, limit: ADMIN_PAGE_SIZE }),
  );

export const getPayment = (paymentId: string, amountPaise?: number) =>
  get(
    `/payments/${pathId(paymentId)}`,
    contract.zAdminBillingGetPaymentResponse,
    contract.zAdminBillingGetPaymentQuery.parse({ amountPaise }),
  );

export const createRefund = (
  paymentId: string,
  input: z.input<typeof contract.zAdminBillingCreateRefundBody>,
  idempotencyKey: string,
) =>
  send(
    "post",
    `/payments/${pathId(paymentId)}/refunds`,
    contract.zAdminBillingCreateRefundResponse,
    contract.zAdminBillingCreateRefundBody.parse(input),
    idempotencyHeaders(idempotencyKey),
  );

export const listOrders = (filters: OrderFilters, cursor?: string) =>
  get(
    "/orders",
    contract.zAdminBillingListOrdersResponse,
    contract.zAdminBillingListOrdersQuery.parse({ ...filters, cursor, limit: ADMIN_PAGE_SIZE }),
  );

export const getOrder = (orderId: string) =>
  get(`/orders/${pathId(orderId)}`, contract.zAdminBillingGetOrderResponse);

export const listRefunds = (filters: RefundFilters, cursor?: string) =>
  get(
    "/refunds",
    contract.zAdminBillingListRefundsResponse,
    contract.zAdminBillingListRefundsQuery.parse({ ...filters, cursor, limit: ADMIN_PAGE_SIZE }),
  );

export const getRefund = (refundId: string) =>
  get(`/refunds/${pathId(refundId)}`, contract.zAdminBillingGetRefundResponse);

export const listSubscriptions = (filters: SubscriptionFilters, cursor?: string) =>
  get(
    "/subscriptions",
    contract.zAdminBillingListSubscriptionsResponse,
    contract.zAdminBillingListSubscriptionsQuery.parse({
      ...filters,
      cursor,
      limit: ADMIN_PAGE_SIZE,
    }),
  );

export const getSubscription = (subscriptionId: string) =>
  get(`/subscriptions/${pathId(subscriptionId)}`, contract.zAdminBillingGetSubscriptionResponse);

export const cancelSubscription = (subscriptionId: string, immediately: boolean) =>
  send(
    "post",
    `/subscriptions/${pathId(subscriptionId)}/cancel`,
    contract.zAdminBillingCancelSubscriptionResponse,
    contract.zAdminBillingCancelSubscriptionBody.parse({ immediately }),
  );

export const listWebhookEvents = (filters: WebhookFilters, cursor?: string) =>
  get(
    "/webhooks",
    contract.zAdminBillingListWebhookEventsResponse,
    contract.zAdminBillingListWebhookEventsQuery.parse({
      ...filters,
      cursor,
      limit: ADMIN_PAGE_SIZE,
    }),
  );

export const getWebhookEvent = (eventId: string) =>
  get(`/webhooks/${pathId(eventId)}`, contract.zAdminBillingGetWebhookEventResponse);

export const reprocessWebhookEvent = (eventId: string) =>
  send(
    "post",
    `/webhooks/${pathId(eventId)}/reprocess`,
    contract.zAdminBillingReprocessWebhookEventResponse,
  );

export const listReconciliationRuns = (filters: RunFilters, cursor?: string) =>
  get(
    "/reconciliation/runs",
    contract.zAdminBillingListReconciliationRunsResponse,
    contract.zAdminBillingListReconciliationRunsQuery.parse({
      ...filters,
      cursor,
      limit: ADMIN_PAGE_SIZE,
    }),
  );

export const getReconciliationRun = (runId: string) =>
  get(`/reconciliation/runs/${pathId(runId)}`, contract.zAdminBillingGetReconciliationRunResponse);

export const downloadReconciliationReport = async (runId: string) =>
  contract.zAdminBillingDownloadReconciliationReportResponse.parse(
    (
      await apiClient.get<unknown>(`${BASE}/reconciliation/runs/${pathId(runId)}/report`, {
        authenticated: true,
        responseType: "text",
        transformResponse: [(data: unknown) => data],
      })
    ).data,
  );

export const getUserCredits = (userId: string, cursor?: string) =>
  get(
    `/users/${pathId(userId)}/credits`,
    contract.zAdminBillingGetUserCreditsResponse,
    contract.zAdminBillingGetUserCreditsQuery.parse({ cursor, limit: ADMIN_PAGE_SIZE }),
  );

export const listUserCreditLedger = (userId: string, cursor?: string) =>
  get(
    `/users/${pathId(userId)}/credits/ledger`,
    contract.zAdminBillingListUserCreditLedgerResponse,
    contract.zAdminBillingListUserCreditLedgerQuery.parse({ cursor, limit: ADMIN_PAGE_SIZE }),
  );

export const adjustUserCredits = (
  userId: string,
  input: z.input<typeof contract.zAdminBillingAdjustUserCreditsBody>,
  idempotencyKey: string,
) =>
  send(
    "post",
    `/users/${pathId(userId)}/credits/adjust`,
    contract.zAdminBillingAdjustUserCreditsResponse,
    contract.zAdminBillingAdjustUserCreditsBody.parse(input),
    idempotencyHeaders(idempotencyKey),
  );
