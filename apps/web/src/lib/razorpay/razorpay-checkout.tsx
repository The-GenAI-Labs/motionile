"use client";

import { useEffect, useRef, useState } from "react";

import type { CheckoutProps } from "@/lib/razorpay/checkout.types";
import { buildRazorpayOptions } from "@/lib/razorpay/checkout-options";
import { CHECKOUT_MESSAGES, CheckoutPanel } from "@/lib/razorpay/checkout-panel";
import { completeCheckout, completionFrom } from "@/lib/razorpay/complete-checkout";
import { loadRazorpayCheckout } from "@/lib/razorpay/load-checkout";
import type { RazorpayInstance } from "@/lib/razorpay/razorpay.types";

type Phase =
  | { kind: "loading" }
  | { kind: "open"; failure: string | null }
  | { kind: "confirming" }
  | { kind: "dismissed"; failure: string | null }
  | { kind: "unavailable" };

const failureMessage = (description: string | undefined): string =>
  description ? `Payment failed: ${description}` : CHECKOUT_MESSAGES.failed;

export function RazorpayCheckout({ target, verify, onFinished, onDismiss }: CheckoutProps) {
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  const latest = useRef({ verify, onFinished });

  useEffect(() => {
    latest.current = { verify, onFinished };
  });

  useEffect(() => {
    let active = true;
    let instance: RazorpayInstance | null = null;
    loadRazorpayCheckout()
      .then((Razorpay) => {
        if (!active) {
          return;
        }
        instance = new Razorpay(
          buildRazorpayOptions(target, {
            onPaid: (response) => {
              if (active) {
                setPhase({ kind: "confirming" });
              }
              void completeCheckout({
                completion: completionFrom(target, response),
                verify: latest.current.verify,
              }).then(() => {
                latest.current.onFinished(target.orderId);
              });
            },
            onDismiss: () => {
              if (active) {
                setPhase((current) =>
                  current.kind === "open"
                    ? { kind: "dismissed", failure: current.failure }
                    : current,
                );
              }
            },
          }),
        );
        instance.on("payment.failed", (response) => {
          if (active) {
            setPhase({ kind: "open", failure: failureMessage(response.error.description) });
          }
        });
        instance.open();
        setPhase({ kind: "open", failure: null });
      })
      .catch(() => {
        if (active) {
          setPhase({ kind: "unavailable" });
        }
      });
    return () => {
      active = false;
      instance?.close();
    };
  }, [target, attempt]);

  const retry = () => {
    setPhase({ kind: "loading" });
    setAttempt((count) => count + 1);
  };

  switch (phase.kind) {
    case "loading":
      return <CheckoutPanel tone="progress" busy message={CHECKOUT_MESSAGES.loading} />;
    case "open":
      return phase.failure ? (
        <CheckoutPanel tone="problem" message={phase.failure} />
      ) : (
        <CheckoutPanel tone="progress" message={CHECKOUT_MESSAGES.open} />
      );
    case "confirming":
      return <CheckoutPanel tone="progress" busy message={CHECKOUT_MESSAGES.confirming} />;
    case "dismissed":
      return (
        <CheckoutPanel
          tone={phase.failure ? "problem" : "progress"}
          message={phase.failure ?? CHECKOUT_MESSAGES.dismissed}
          onRetry={retry}
          onCancel={onDismiss}
        />
      );
    case "unavailable":
      return (
        <CheckoutPanel
          tone="problem"
          message={CHECKOUT_MESSAGES.unavailable}
          onRetry={retry}
          onCancel={onDismiss}
        />
      );
  }
}
