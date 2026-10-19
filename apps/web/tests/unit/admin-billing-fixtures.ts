import type {
  AdminPaymentDetail,
  AdminProductDetail,
  AdminRun,
  AdminWebhookEventDetail,
} from "@/features/admin-billing/types/admin-billing.types";

const uuid = (suffix: number): string =>
  `0197c5a2-1b2c-7d3e-8f40-${String(suffix).padStart(12, "0")}`;

export const PAYMENT_ID = uuid(1);
export const PRODUCT_ID = uuid(2);
export const RUN_ID = uuid(3);
export const EVENT_ID = uuid(4);
export const USER_ID = uuid(5);

export const paymentDetail = (overrides: Partial<AdminPaymentDetail> = {}): AdminPaymentDetail => ({
  id: PAYMENT_ID,
  amountPaise: 49_900,
  capturedAt: "2026-10-17T10:30:00Z",
  clawbackPreview: { amountPaise: 49_900, creditsToClawBack: 300 },
  createdAt: "2026-10-17T10:30:00Z",
  creditsGranted: 300,
  currency: "INR",
  errorCode: null,
  errorDescription: null,
  feePaise: null,
  flagged: false,
  lot: null,
  method: "upi",
  order: null,
  orderId: null,
  pendingRefundPaise: 0,
  productCode: "pack_starter",
  productName: "Starter",
  razorpayPaymentId: "pay_Abc123",
  refundablePaise: 49_900,
  refundedPaise: 0,
  refunds: [],
  status: "captured",
  subscription: null,
  subscriptionId: null,
  taxPaise: null,
  userId: USER_ID,
  ...overrides,
});

export const productDetail = (overrides: Partial<AdminProductDetail> = {}): AdminProductDetail => ({
  id: PRODUCT_ID,
  code: "pack_starter",
  createdAt: "2026-10-01T10:00:00Z",
  creditsGranted: 100,
  currency: "INR",
  description: "Starter pack",
  features: ["Credits never expire"],
  interval: null,
  isActive: true,
  isSample: false,
  isUsed: false,
  kind: "credit_pack",
  name: "Starter",
  planKey: null,
  pricePaise: 19_900,
  razorpayPlanId: null,
  sortOrder: 10,
  supersededBy: [],
  supersedes: null,
  supersedesProductId: null,
  updatedAt: "2026-10-01T10:00:00Z",
  version: 3,
  ...overrides,
});

export const run = (overrides: Partial<AdminRun> = {}): AdminRun => ({
  id: RUN_ID,
  checkedCount: 40,
  createdAt: "2026-10-17T04:00:00Z",
  error: null,
  finishedAt: "2026-10-17T04:01:00Z",
  hasReport: true,
  mismatchCount: 2,
  periodEnd: null,
  periodStart: null,
  repairedCount: 0,
  startedAt: "2026-10-17T04:00:00Z",
  status: "completed",
  summary: { missing: 2 },
  type: "settlement",
  ...overrides,
});

export const webhookEvent = (
  overrides: Partial<AdminWebhookEventDetail> = {},
): AdminWebhookEventDetail => ({
  id: EVENT_ID,
  attempts: 3,
  eventCreatedAt: null,
  eventId: "evt_123",
  eventType: "payment.captured",
  ignoredReason: null,
  lastError: "boom",
  payload: { event: "payment.captured" },
  processedAt: null,
  provider: "razorpay",
  receivedAt: "2026-10-17T10:30:00Z",
  status: "failed",
  ...overrides,
});
