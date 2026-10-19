import { z } from "zod";

import { apiClient } from "@/lib/api/client";

const FAKE_RAZORPAY_PATH = "/v1/_test/razorpay";

const emittedWebhookSchema = z.object({
  eventId: z.string(),
  event: z.string(),
  statusCodes: z.array(z.number()),
});

const payOrderResultSchema = z.object({
  razorpay_order_id: z.string(),
  razorpay_payment_id: z.string(),
  razorpay_signature: z.string().nullable(),
  paymentStatus: z.string(),
  webhooks: z.array(emittedWebhookSchema),
});

const authorizeResultSchema = z.object({
  razorpay_payment_id: z.string(),
  razorpay_subscription_id: z.string(),
  razorpay_signature: z.string(),
  subscriptionStatus: z.string(),
  webhooks: z.array(emittedWebhookSchema),
});

const transitionResultSchema = z.object({
  subscriptionStatus: z.string(),
  paidCount: z.number(),
  razorpayPaymentId: z.string().nullable(),
  webhooks: z.array(emittedWebhookSchema),
});

export type FakePaymentOutcome = "success" | "failure";

export type FakeOrderWebhook = "payment.captured" | "order.paid" | "payment.failed";

export type FakeSubscriptionEvent = "activated" | "charged";

const post = async <Schema extends z.ZodType>(
  path: string,
  body: unknown,
  schema: Schema,
): Promise<z.output<Schema>> =>
  schema.parse(
    (
      await apiClient.post<unknown>(`${FAKE_RAZORPAY_PATH}${path}`, body, {
        skipAuthRefresh: true,
      })
    ).data,
  );

export const payFakeOrder = (
  razorpayOrderId: string,
  outcome: FakePaymentOutcome,
  webhooks: readonly FakeOrderWebhook[] = [],
) =>
  post(
    `/orders/${encodeURIComponent(razorpayOrderId)}/pay`,
    { outcome, webhooks },
    payOrderResultSchema,
  );

export const authorizeFakeSubscription = (razorpaySubscriptionId: string) =>
  post(
    `/subscriptions/${encodeURIComponent(razorpaySubscriptionId)}/authorize`,
    { webhooks: [] },
    authorizeResultSchema,
  );

export const transitionFakeSubscription = (
  razorpaySubscriptionId: string,
  event: FakeSubscriptionEvent,
) =>
  post(
    `/subscriptions/${encodeURIComponent(razorpaySubscriptionId)}/transition`,
    { event, emit: true },
    transitionResultSchema,
  );

export const deliverFakeSubscriptionCharge = (
  razorpaySubscriptionId: string,
  razorpayPaymentId: string,
) =>
  post(
    "/webhooks",
    {
      event: "subscription.charged",
      subscriptionId: razorpaySubscriptionId,
      paymentId: razorpayPaymentId,
    },
    emittedWebhookSchema,
  );
