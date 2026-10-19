import type {
  zAdjustCreditsResponse,
  zAdminLedgerEntryResponse,
  zAdminLotResponse,
  zAdminOrderDetailResponse,
  zAdminOrderResponse,
  zAdminPaymentDetailResponse,
  zAdminPaymentResponse,
  zAdminProductDetailResponse,
  zAdminProductResponse,
  zAdminRefundResponse,
  zAdminRunResponse,
  zAdminSubscriptionDetailResponse,
  zAdminSubscriptionResponse,
  zAdminUserCreditsResponse,
  zAdminWebhookEventDetailResponse,
  zAdminWebhookEventResponse,
  zCreditsAnalyticsResponse,
  zFlagReasonName,
  zIntervalName,
  zOrderStatusName,
  zPaymentStatusName,
  zProductKindName,
  zRefundStatusName,
  zRevenueAnalyticsResponse,
  zRunStatusName,
  zRunTypeName,
  zSubscriptionAnalyticsResponse,
  zSubscriptionStatusName,
  zWebhookReprocessResponse,
  zWebhookStatusName,
} from "@motionile/api-contract";
import type { z } from "zod";

export type AdminProduct = z.output<typeof zAdminProductResponse>;
export type AdminProductDetail = z.output<typeof zAdminProductDetailResponse>;
export type AdminOrder = z.output<typeof zAdminOrderResponse>;
export type AdminOrderDetail = z.output<typeof zAdminOrderDetailResponse>;
export type AdminPayment = z.output<typeof zAdminPaymentResponse>;
export type AdminPaymentDetail = z.output<typeof zAdminPaymentDetailResponse>;
export type AdminRefund = z.output<typeof zAdminRefundResponse>;
export type AdminSubscription = z.output<typeof zAdminSubscriptionResponse>;
export type AdminSubscriptionDetail = z.output<typeof zAdminSubscriptionDetailResponse>;
export type AdminWebhookEvent = z.output<typeof zAdminWebhookEventResponse>;
export type AdminWebhookEventDetail = z.output<typeof zAdminWebhookEventDetailResponse>;
export type AdminRun = z.output<typeof zAdminRunResponse>;
export type AdminLot = z.output<typeof zAdminLotResponse>;
export type AdminLedgerEntry = z.output<typeof zAdminLedgerEntryResponse>;
export type AdminUserCredits = z.output<typeof zAdminUserCreditsResponse>;
export type AdjustCreditsResult = z.output<typeof zAdjustCreditsResponse>;
export type WebhookReprocessResult = z.output<typeof zWebhookReprocessResponse>;
export type RevenueAnalytics = z.output<typeof zRevenueAnalyticsResponse>;
export type SubscriptionAnalytics = z.output<typeof zSubscriptionAnalyticsResponse>;
export type CreditsAnalytics = z.output<typeof zCreditsAnalyticsResponse>;

export type ProductKind = z.output<typeof zProductKindName>;
export type ProductInterval = z.output<typeof zIntervalName>;
export type OrderStatus = z.output<typeof zOrderStatusName>;
export type PaymentStatus = z.output<typeof zPaymentStatusName>;
export type RefundStatus = z.output<typeof zRefundStatusName>;
export type SubscriptionStatus = z.output<typeof zSubscriptionStatusName>;
export type WebhookStatus = z.output<typeof zWebhookStatusName>;
export type RunStatus = z.output<typeof zRunStatusName>;
export type RunType = z.output<typeof zRunTypeName>;
export type FlagReason = z.output<typeof zFlagReasonName>;

export interface DateRange {
  from: string;
  to: string;
}

export interface ProductFilters {
  kind?: ProductKind;
  isActive?: boolean;
  isSample?: boolean;
  search?: string;
}

export interface PaymentFilters {
  status?: PaymentStatus;
  userId?: string;
  orderId?: string;
  createdFrom?: string;
  createdTo?: string;
  flagged?: boolean;
}

export interface OrderFilters {
  status?: OrderStatus;
  flagged?: boolean;
  userId?: string;
}

export interface RefundFilters {
  status?: RefundStatus;
  paymentId?: string;
}

export interface SubscriptionFilters {
  status?: SubscriptionStatus;
  planKey?: string;
  userId?: string;
}

export interface WebhookFilters {
  status?: WebhookStatus;
  eventType?: string;
  receivedFrom?: string;
  receivedTo?: string;
}

export interface RunFilters {
  type?: RunType;
  status?: RunStatus;
  hasMismatches?: boolean;
}
