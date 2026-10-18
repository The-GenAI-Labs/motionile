import { Loader2Icon } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";

export const CHECKOUT_MESSAGES = {
  loading: "Opening secure checkout…",
  open: "Complete your payment in the checkout window. Keep this page open until it finishes.",
  confirming: "Confirming your payment…",
  dismissed:
    "Checkout was closed before the payment finished. Nothing was charged, and you can try again with the same order.",
  unavailable: "Secure checkout could not be loaded. Check your connection and try again.",
  failed: "The payment did not go through. You can try again with the same order.",
} as const;

export type CheckoutPanelTone = "progress" | "problem";

interface CheckoutPanelProps {
  tone: CheckoutPanelTone;
  message: string;
  busy?: boolean;
  onRetry?: () => void;
  onCancel?: () => void;
  children?: ReactNode;
}

export function CheckoutPanel({
  tone,
  message,
  busy = false,
  onRetry,
  onCancel,
  children,
}: CheckoutPanelProps) {
  return (
    <section
      aria-labelledby="checkout-panel-title"
      className="space-y-4 rounded-xl border bg-surface p-6"
    >
      <h2 id="checkout-panel-title" className="font-semibold">
        Secure checkout
      </h2>
      <p
        role={tone === "problem" ? "alert" : "status"}
        className={
          tone === "problem"
            ? "flex items-center gap-2 text-sm text-destructive"
            : "flex items-center gap-2 text-sm text-subtle-foreground"
        }
      >
        {busy ? (
          <Loader2Icon
            aria-hidden="true"
            className="size-4 animate-spin motion-reduce:animate-none"
          />
        ) : null}
        {message}
      </p>
      {children}
      {onRetry || onCancel ? (
        <div className="flex flex-wrap gap-2">
          {onRetry ? <Button onClick={onRetry}>Try again</Button> : null}
          {onCancel ? (
            <Button variant="outline" onClick={onCancel}>
              Cancel
            </Button>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
