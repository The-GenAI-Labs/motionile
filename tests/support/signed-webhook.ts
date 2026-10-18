import { createHmac, randomUUID } from "node:crypto";

import type { APIRequestContext, APIResponse } from "@playwright/test";

export const WEBHOOK_PATH = "/v1/webhooks/razorpay";
export const SIGNATURE_HEADER = "X-Razorpay-Signature";
export const EVENT_ID_HEADER = "X-Razorpay-Event-Id";

const DEVELOPMENT_WEBHOOK_SECRET = "motionile-development-razorpay-webhook-secret";
const apiBaseUrl = process.env["API_BASE_URL"] ?? "http://localhost:8000";

type WebhookEvent = "payment.captured" | "payment.failed";

export interface PaymentFacts {
  id: string;
  orderId: string;
  amountPaise: number;
  currency: string;
}

export interface WebhookDelivery {
  eventId?: string | null;
  signature?: string | null;
  secret?: string;
}

export interface WebhookReceipt {
  status: string;
}

export function webhookSecret(): string {
  return process.env["BILLING_RAZORPAY_WEBHOOK_SECRET"] ?? DEVELOPMENT_WEBHOOK_SECRET;
}

export function signWebhook(body: string, secret: string = webhookSecret()): string {
  return createHmac("sha256", secret).update(body).digest("hex");
}

export function newEventId(): string {
  return `evt_${randomUUID().replaceAll("-", "")}`;
}

function paymentWebhook(event: WebhookEvent, facts: PaymentFacts): string {
  const captured = event === "payment.captured";
  const createdAt = Math.floor(Date.now() / 1000);
  return JSON.stringify({
    entity: "event",
    account_id: "acc_motionile_e2e",
    event,
    contains: ["payment"],
    payload: {
      payment: {
        entity: {
          id: facts.id,
          entity: "payment",
          amount: facts.amountPaise,
          currency: facts.currency,
          status: captured ? "captured" : "failed",
          order_id: facts.orderId,
          method: "card",
          captured,
          amount_refunded: 0,
          refund_status: null,
          fee: null,
          tax: null,
          notes: {},
          created_at: createdAt,
        },
      },
    },
    created_at: createdAt,
  });
}

export function capturedPaymentWebhook(facts: PaymentFacts): string {
  return paymentWebhook("payment.captured", facts);
}

export function failedPaymentWebhook(facts: PaymentFacts): string {
  return paymentWebhook("payment.failed", facts);
}

export function unknownOrderFailure(): string {
  const suffix = randomUUID().replaceAll("-", "").slice(0, 16);
  return failedPaymentWebhook({
    id: `pay_unknown${suffix}`,
    orderId: `order_unknown${suffix}`,
    amountPaise: 19900,
    currency: "INR",
  });
}

export async function postWebhook(
  request: APIRequestContext,
  body: string,
  delivery: WebhookDelivery = {},
): Promise<APIResponse> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const signature =
    delivery.signature === undefined ? signWebhook(body, delivery.secret) : delivery.signature;
  if (signature !== null) headers[SIGNATURE_HEADER] = signature;
  const eventId = delivery.eventId === undefined ? newEventId() : delivery.eventId;
  if (eventId !== null) headers[EVENT_ID_HEADER] = eventId;
  return request.post(new URL(WEBHOOK_PATH, apiBaseUrl).toString(), {
    headers,
    data: Buffer.from(body),
  });
}

export async function receiptOf(response: APIResponse): Promise<string> {
  return ((await response.json()) as WebhookReceipt).status;
}
