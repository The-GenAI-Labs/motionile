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

export const adminBillingKeys = {
  all: ["admin-billing"] as const,
  analytics: () => [...adminBillingKeys.all, "analytics"] as const,
  revenue: (range: DateRange) => [...adminBillingKeys.analytics(), "revenue", range] as const,
  subscriptionAnalytics: () => [...adminBillingKeys.analytics(), "subscriptions"] as const,
  creditsAnalytics: (range: DateRange) =>
    [...adminBillingKeys.analytics(), "credits", range] as const,
  products: () => [...adminBillingKeys.all, "products"] as const,
  productList: (filters: ProductFilters) =>
    [...adminBillingKeys.products(), "list", filters] as const,
  product: (productId: string) => [...adminBillingKeys.products(), "detail", productId] as const,
  payments: () => [...adminBillingKeys.all, "payments"] as const,
  paymentList: (filters: PaymentFilters) =>
    [...adminBillingKeys.payments(), "list", filters] as const,
  payment: (paymentId: string, amountPaise?: number) =>
    [...adminBillingKeys.payments(), "detail", paymentId, amountPaise ?? null] as const,
  orders: () => [...adminBillingKeys.all, "orders"] as const,
  orderList: (filters: OrderFilters) => [...adminBillingKeys.orders(), "list", filters] as const,
  order: (orderId: string) => [...adminBillingKeys.orders(), "detail", orderId] as const,
  refunds: () => [...adminBillingKeys.all, "refunds"] as const,
  refundList: (filters: RefundFilters) => [...adminBillingKeys.refunds(), "list", filters] as const,
  refund: (refundId: string) => [...adminBillingKeys.refunds(), "detail", refundId] as const,
  subscriptions: () => [...adminBillingKeys.all, "subscriptions"] as const,
  subscriptionList: (filters: SubscriptionFilters) =>
    [...adminBillingKeys.subscriptions(), "list", filters] as const,
  subscription: (subscriptionId: string) =>
    [...adminBillingKeys.subscriptions(), "detail", subscriptionId] as const,
  webhooks: () => [...adminBillingKeys.all, "webhooks"] as const,
  webhookList: (filters: WebhookFilters) =>
    [...adminBillingKeys.webhooks(), "list", filters] as const,
  webhook: (eventId: string) => [...adminBillingKeys.webhooks(), "detail", eventId] as const,
  runs: () => [...adminBillingKeys.all, "runs"] as const,
  runList: (filters: RunFilters) => [...adminBillingKeys.runs(), "list", filters] as const,
  run: (runId: string) => [...adminBillingKeys.runs(), "detail", runId] as const,
  credits: () => [...adminBillingKeys.all, "credits"] as const,
  userCredits: (userId: string) => [...adminBillingKeys.credits(), "wallet", userId] as const,
  userLedger: (userId: string) => [...adminBillingKeys.credits(), "ledger", userId] as const,
};
