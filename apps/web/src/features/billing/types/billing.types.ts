import type {
  zCheckoutResponse,
  zCurrentSubscriptionResponse,
  zHistoryItemResponse,
  zOrderResponse,
  zOrderStatusName,
  zProductResponse,
  zProductsResponse,
  zSubscriptionCheckoutResponse,
  zSubscriptionResponse,
  zSubscriptionStatusName,
  zVerifyPaymentResponse,
} from "@motionile/api-contract";
import type { z } from "zod";

export type Product = z.output<typeof zProductResponse>;
export type Products = z.output<typeof zProductsResponse>;
export type Order = z.output<typeof zOrderResponse>;
export type OrderStatus = z.output<typeof zOrderStatusName>;
export type OrderCheckout = z.output<typeof zCheckoutResponse>;
export type SubscriptionCheckout = z.output<typeof zSubscriptionCheckoutResponse>;
export type Subscription = z.output<typeof zSubscriptionResponse>;
export type SubscriptionStatus = z.output<typeof zSubscriptionStatusName>;
export type CurrentSubscription = z.output<typeof zCurrentSubscriptionResponse>;
export type HistoryItem = z.output<typeof zHistoryItemResponse>;
export type PaymentVerification = z.output<typeof zVerifyPaymentResponse>;

export type PurchaseKind = "credit_pack" | "subscription";

export interface PlanGroup {
  planKey: string;
  name: string;
  byInterval: Partial<Record<"month" | "year", Product>>;
}
