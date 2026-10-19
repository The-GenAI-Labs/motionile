"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import {
  createOrder,
  createSubscription,
  verifyPayment,
  verifySubscription,
} from "@/features/billing/api/billing.api";
import { isRetryableCheckoutError } from "@/features/billing/errors";
import { billingKeys } from "@/features/billing/query-keys";
import type {
  OrderCheckout,
  PurchaseKind,
  SubscriptionCheckout,
} from "@/features/billing/types/billing.types";
import { creditsKeys } from "@/features/credits/query-keys";
import type { CheckoutCompletion, CheckoutTarget } from "@/lib/razorpay/checkout.types";

export const toOrderTarget = (checkout: OrderCheckout): CheckoutTarget => ({
  kind: "order",
  orderId: checkout.orderId,
  keyId: checkout.keyId,
  razorpayOrderId: checkout.razorpayOrderId,
  amountPaise: checkout.amountPaise,
  currency: checkout.currency,
  description: checkout.description,
  prefill: checkout.prefill,
});

export const toSubscriptionTarget = (checkout: SubscriptionCheckout): CheckoutTarget => ({
  kind: "subscription",
  orderId: checkout.orderId,
  keyId: checkout.keyId,
  razorpaySubscriptionId: checkout.razorpaySubscriptionId,
  description: checkout.description,
  prefill: checkout.prefill,
});

interface PurchaseRequest {
  productCode: string;
  idempotencyKey: string;
}

interface PendingAttempt {
  kind: PurchaseKind;
  productCode: string;
  idempotencyKey: string;
}

export const useCheckout = () => {
  const client = useQueryClient();
  const [target, setTarget] = useState<CheckoutTarget | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [starting, setStarting] = useState(false);
  const pendingAttempt = useRef<PendingAttempt | null>(null);

  const orderMutation = useMutation({
    mutationFn: (input: PurchaseRequest) => createOrder(input),
  });
  const subscriptionMutation = useMutation({
    mutationFn: (input: PurchaseRequest) => createSubscription(input),
  });
  const paymentVerification = useMutation({
    mutationFn: (input: Parameters<typeof verifyPayment>[0]) => verifyPayment(input),
  });
  const subscriptionVerification = useMutation({
    mutationFn: (input: Parameters<typeof verifySubscription>[0]) => verifySubscription(input),
  });

  const refreshAfterVerification = () =>
    Promise.all([
      client.invalidateQueries({ queryKey: creditsKeys.wallet() }),
      client.invalidateQueries({ queryKey: billingKeys.history() }),
      client.invalidateQueries({ queryKey: billingKeys.subscription() }),
    ]);

  const start = async (kind: PurchaseKind, productCode: string): Promise<void> => {
    const previous = pendingAttempt.current;
    const attempt: PendingAttempt =
      previous?.kind === kind && previous.productCode === productCode
        ? previous
        : { kind, productCode, idempotencyKey: crypto.randomUUID() };
    pendingAttempt.current = attempt;
    setError(null);
    setStarting(true);
    try {
      const request = { productCode, idempotencyKey: attempt.idempotencyKey };
      setTarget(
        kind === "credit_pack"
          ? toOrderTarget(await orderMutation.mutateAsync(request))
          : toSubscriptionTarget(await subscriptionMutation.mutateAsync(request)),
      );
      pendingAttempt.current = null;
    } catch (failure) {
      if (!isRetryableCheckoutError(failure)) {
        pendingAttempt.current = null;
      }
      setError(failure);
    } finally {
      setStarting(false);
    }
  };

  const verify = async (completion: CheckoutCompletion): Promise<void> => {
    if (completion.kind === "order") {
      await paymentVerification.mutateAsync({
        razorpayOrderId: completion.razorpayOrderId,
        razorpayPaymentId: completion.razorpayPaymentId,
        razorpaySignature: completion.razorpaySignature,
      });
    } else {
      await subscriptionVerification.mutateAsync({
        razorpaySubscriptionId: completion.razorpaySubscriptionId,
        razorpayPaymentId: completion.razorpayPaymentId,
        razorpaySignature: completion.razorpaySignature,
      });
    }
    void refreshAfterVerification();
  };

  const close = () => {
    setTarget(null);
  };

  return { target, error, starting, start, verify, close };
};

export type CheckoutController = ReturnType<typeof useCheckout>;
