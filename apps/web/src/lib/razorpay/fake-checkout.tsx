"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type {
  CheckoutCompletion,
  CheckoutProps,
  CheckoutTarget,
} from "@/lib/razorpay/checkout.types";
import { CHECKOUT_MESSAGES, CheckoutPanel } from "@/lib/razorpay/checkout-panel";
import { completeCheckout } from "@/lib/razorpay/complete-checkout";
import {
  authorizeFakeSubscription,
  deliverFakeSubscriptionCharge,
  payFakeOrder,
  transitionFakeSubscription,
} from "@/lib/razorpay/fake-api";

type FakeAction = "pay" | "fail" | "pay-skip-verification";

type Phase = { kind: "open"; notice: string | null } | { kind: "working" } | { kind: "dismissed" };

const SIMULATED_FAILURE = "Payment failed: the simulated payment was declined.";

const SIMULATION_ERROR = "The simulated checkout could not reach the API. Try again.";

const settleOrder = async (
  target: Extract<CheckoutTarget, { kind: "order" }>,
  action: FakeAction,
  props: CheckoutProps,
): Promise<string | null> => {
  if (action === "fail") {
    await payFakeOrder(target.razorpayOrderId, "failure");
    return SIMULATED_FAILURE;
  }
  if (action === "pay-skip-verification") {
    await payFakeOrder(target.razorpayOrderId, "success", ["payment.captured", "order.paid"]);
    return null;
  }
  const paid = await payFakeOrder(target.razorpayOrderId, "success");
  await completeCheckout({
    completion: {
      kind: "order",
      razorpayOrderId: paid.razorpay_order_id,
      razorpayPaymentId: paid.razorpay_payment_id,
      razorpaySignature: paid.razorpay_signature ?? "",
    },
    verify: props.verify,
  });
  return null;
};

const settleSubscription = async (
  target: Extract<CheckoutTarget, { kind: "subscription" }>,
  action: FakeAction,
  props: CheckoutProps,
): Promise<string | null> => {
  if (action === "fail") {
    return SIMULATED_FAILURE;
  }
  const authorized = await authorizeFakeSubscription(target.razorpaySubscriptionId);
  const activate = async () => {
    await transitionFakeSubscription(target.razorpaySubscriptionId, "activated");
    await deliverFakeSubscriptionCharge(
      target.razorpaySubscriptionId,
      authorized.razorpay_payment_id,
    );
  };
  if (action === "pay-skip-verification") {
    await activate();
    return null;
  }
  const completion: CheckoutCompletion = {
    kind: "subscription",
    razorpaySubscriptionId: authorized.razorpay_subscription_id,
    razorpayPaymentId: authorized.razorpay_payment_id,
    razorpaySignature: authorized.razorpay_signature,
  };
  await completeCheckout({
    completion,
    verify: async (value) => {
      try {
        await props.verify(value);
      } finally {
        await activate();
      }
    },
  });
  return null;
};

export function FakeCheckout(props: CheckoutProps) {
  const { target, onFinished, onDismiss } = props;
  const [phase, setPhase] = useState<Phase>({ kind: "open", notice: null });

  const run = async (action: FakeAction) => {
    setPhase({ kind: "working" });
    try {
      const notice =
        target.kind === "order"
          ? await settleOrder(target, action, props)
          : await settleSubscription(target, action, props);
      if (notice === null) {
        onFinished(target.orderId);
        return;
      }
      setPhase({ kind: "open", notice });
    } catch {
      setPhase({ kind: "open", notice: SIMULATION_ERROR });
    }
  };

  const close = () => {
    setPhase({ kind: "dismissed" });
  };

  if (phase.kind === "dismissed") {
    return (
      <CheckoutPanel
        tone="progress"
        message={CHECKOUT_MESSAGES.dismissed}
        onRetry={() => {
          setPhase({ kind: "open", notice: null });
        }}
        onCancel={onDismiss}
      />
    );
  }

  const working = phase.kind === "working";
  const notice = phase.kind === "open" ? phase.notice : null;

  return (
    <>
      <CheckoutPanel
        tone={notice ? "problem" : "progress"}
        busy={working}
        message={working ? CHECKOUT_MESSAGES.confirming : (notice ?? CHECKOUT_MESSAGES.open)}
      />
      <Dialog
        open
        onOpenChange={(open) => {
          if (!open && !working) {
            close();
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Simulated checkout</DialogTitle>
            <DialogDescription>
              {target.description}. This simulated checkout replaces the payment provider while fake
              providers are enabled, and no money moves.
            </DialogDescription>
          </DialogHeader>
          {notice ? (
            <p role="alert" className="text-sm text-destructive">
              {notice}
            </p>
          ) : null}
          <DialogFooter className="sm:flex-wrap">
            <Button
              disabled={working}
              onClick={() => {
                void run("pay");
              }}
            >
              Pay successfully
            </Button>
            <Button
              variant="outline"
              disabled={working}
              onClick={() => {
                void run("pay-skip-verification");
              }}
            >
              Pay and skip verification
            </Button>
            <Button
              variant="outline"
              disabled={working}
              onClick={() => {
                void run("fail");
              }}
            >
              Fail payment
            </Button>
            <Button variant="outline" disabled={working} onClick={close}>
              Close without paying
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
