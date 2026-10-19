"use client";

import { Loader2Icon } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { BillingError } from "@/features/billing/components/billing-error";
import { subscriptionStatusLabels } from "@/features/billing/components/subscription-card";
import { useOrderStatus } from "@/features/billing/hooks/use-order-status";
import { useSubscription } from "@/features/billing/hooks/use-subscription";
import type { Order } from "@/features/billing/types/billing.types";
import { ApiError } from "@/lib/api/api-error";
import { formatCredits, formatPaise } from "@/lib/utils/format";

interface OrderStatusProps {
  orderId: string;
}

interface StatusPanelProps {
  title: string;
  tone: "progress" | "success" | "problem";
  children: ReactNode;
  actions?: ReactNode;
}

function StatusPanel({ title, tone, children, actions }: StatusPanelProps) {
  const toneClass =
    tone === "success" ? "text-success" : tone === "problem" ? "text-destructive" : "";
  return (
    <section
      aria-labelledby="order-status-title"
      className="space-y-4 rounded-xl border bg-surface p-6"
    >
      <h2 id="order-status-title" className={`text-xl font-semibold ${toneClass}`}>
        {title}
      </h2>
      <div
        role={tone === "problem" ? "alert" : "status"}
        aria-live={tone === "problem" ? "assertive" : "polite"}
        className="space-y-2 text-sm text-subtle-foreground"
      >
        {children}
      </div>
      {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
    </section>
  );
}

function Waiting({ message }: { message: string }) {
  return (
    <p className="flex items-center gap-2">
      <Loader2Icon aria-hidden="true" className="size-4 animate-spin motion-reduce:animate-none" />
      {message}
    </p>
  );
}

function PaidActions() {
  return (
    <>
      <Button asChild>
        <Link href="/billing">View billing overview</Link>
      </Button>
      <Button asChild variant="outline">
        <Link href={{ pathname: "/create" }}>Create a video</Link>
      </Button>
    </>
  );
}

function SubscriptionProgress() {
  const subscription = useSubscription();
  const current = subscription.data?.subscription;
  if (!current) {
    return null;
  }
  return (
    <p>
      {current.product.name}: {subscriptionStatusLabels[current.status]}
    </p>
  );
}

function PaidPanel({ order }: { order: Order }) {
  return (
    <StatusPanel title="Payment received" tone="success" actions={<PaidActions />}>
      <p>
        We received {formatPaise(order.amountPaise)} (incl. GST) for {order.productName}.
      </p>
      {order.kind === "credit_pack" ? (
        <p>{formatCredits(order.creditsGranted)} credits were added to your wallet.</p>
      ) : (
        <>
          <p>Your subscription credits are added as each billing period is charged.</p>
          <SubscriptionProgress />
        </>
      )}
    </StatusPanel>
  );
}

function retryHref(order: Order): "/billing/credits" | "/billing/plans" {
  return order.kind === "credit_pack" ? "/billing/credits" : "/billing/plans";
}

function EndedPanel({ order, title, message }: { order: Order; title: string; message: string }) {
  return (
    <StatusPanel
      title={title}
      tone="problem"
      actions={
        <Button asChild>
          <Link href={retryHref(order)}>Try again</Link>
        </Button>
      }
    >
      <p>{message}</p>
      <p>If you were charged, the payment will be refunded or applied automatically.</p>
    </StatusPanel>
  );
}

export function OrderStatus({ orderId }: OrderStatusProps) {
  const { query, exhausted, restart } = useOrderStatus(orderId);

  if (query.isError) {
    const error = ApiError.from(query.error);
    if (error.status === 404) {
      return (
        <StatusPanel
          title="Order not found"
          tone="problem"
          actions={
            <Button asChild variant="outline">
              <Link href="/billing/history">View payment history</Link>
            </Button>
          }
        >
          <p>We could not find that order on your account.</p>
        </StatusPanel>
      );
    }
    if (query.data === undefined) {
      return (
        <BillingError
          error={query.error}
          onRetry={() => {
            void query.refetch();
          }}
        />
      );
    }
  }

  if (query.data === undefined) {
    return (
      <StatusPanel title="Checking your payment" tone="progress">
        <Waiting message="Checking your payment…" />
      </StatusPanel>
    );
  }

  const order = query.data;
  switch (order.status) {
    case "paid":
      return <PaidPanel order={order} />;
    case "failed":
      return (
        <EndedPanel
          order={order}
          title="Payment failed"
          message={order.failureReason ?? "The payment did not go through, and nothing was added."}
        />
      );
    case "expired":
      return (
        <EndedPanel
          order={order}
          title="Order expired"
          message="This order expired before a payment was received."
        />
      );
    case "cancelled":
      return (
        <EndedPanel
          order={order}
          title="Order cancelled"
          message="This order was cancelled and no payment was taken."
        />
      );
    case "created":
    case "pending":
      return exhausted ? (
        <StatusPanel
          title="Still processing"
          tone="progress"
          actions={
            <>
              <Button
                onClick={() => {
                  void restart();
                }}
              >
                Check again
              </Button>
              <Button asChild variant="outline">
                <Link href="/billing/history">View payment history</Link>
              </Button>
            </>
          }
        >
          <p>
            Your payment for {order.productName} is taking longer than usual to confirm. If you were
            charged, your credits are added automatically as soon as the payment is confirmed.
          </p>
        </StatusPanel>
      ) : (
        <StatusPanel title="Confirming your payment" tone="progress">
          <Waiting message={`Waiting for confirmation of ${order.productName}…`} />
        </StatusPanel>
      );
  }
}
