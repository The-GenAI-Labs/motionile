"use client";

import { type ReactNode, useState } from "react";

import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { BillingError } from "@/features/billing/components/billing-error";
import { CheckoutHost } from "@/features/billing/components/checkout-host";
import { IntervalToggle } from "@/features/billing/components/interval-toggle";
import { PlanCard } from "@/features/billing/components/plan-card";
import {
  SubscriptionCard,
  subscriptionEndDate,
} from "@/features/billing/components/subscription-card";
import { useAutoStartCheckout } from "@/features/billing/hooks/use-auto-start-checkout";
import { useCheckout } from "@/features/billing/hooks/use-checkout";
import { useProducts } from "@/features/billing/hooks/use-products";
import {
  useCancelSubscription,
  useChangeSubscription,
  useSubscription,
} from "@/features/billing/hooks/use-subscription";
import {
  availableIntervals,
  type BillingInterval,
  groupPlans,
} from "@/features/billing/plan-groups";
import type { PlanGroup, Product, Subscription } from "@/features/billing/types/billing.types";
import { formatDate } from "@/lib/utils/format";

interface PlansManagerProps {
  requestedPlan?: string | null;
}

const isChangeable = (subscription: Subscription): boolean =>
  subscription.status === "active" && !subscription.cancelAtPeriodEnd;

const cancelDescription = (subscription: Subscription): string => {
  const endDate = subscriptionEndDate(subscription);
  if (subscription.status === "active" && endDate) {
    return `Your plan stays active until ${formatDate(endDate)}. You keep your subscription credits until then and you will not be charged again.`;
  }
  return "This subscription has not started billing yet, so it is cancelled immediately and you will not be charged.";
};

const preferredInterval = (
  subscription: Subscription | null,
  requested: Product | undefined,
): BillingInterval => {
  const interval = subscription?.product.interval ?? requested?.interval ?? "month";
  return interval === "year" ? "year" : "month";
};

export function PlansManager({ requestedPlan = null }: PlansManagerProps) {
  const products = useProducts();
  const subscriptionQuery = useSubscription();
  const checkout = useCheckout();
  const cancel = useCancelSubscription();
  const change = useChangeSubscription();
  const [chosenInterval, setChosenInterval] = useState<BillingInterval | null>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const subscription = subscriptionQuery.data?.subscription ?? null;
  const plans = products.data?.subscriptions;
  const { unavailable } = useAutoStartCheckout({
    kind: "subscription",
    requestedCode: requestedPlan,
    products: plans,
    ready: subscriptionQuery.isSuccess && subscription === null,
    checkout,
    cleanPath: "/billing/plans",
  });

  if (products.isPending || subscriptionQuery.isPending) {
    return (
      <div className="space-y-4" role="status" aria-label="Loading plans">
        <Skeleton className="h-40" />
        <Skeleton className="h-72" />
      </div>
    );
  }
  if (products.isError || subscriptionQuery.isError) {
    return (
      <BillingError
        error={products.error ?? subscriptionQuery.error}
        onRetry={() => {
          void products.refetch();
          void subscriptionQuery.refetch();
        }}
      />
    );
  }

  const groups = groupPlans(products.data.subscriptions);
  const intervals = availableIntervals(groups);
  const requestedProduct = products.data.subscriptions.find(
    (product) => product.code === requestedPlan,
  );
  const interval = chosenInterval ?? preferredInterval(subscription, requestedProduct);
  const busy = checkout.starting || checkout.target !== null;

  const cancelSubscription = async () => {
    setActionError(null);
    setNotice(null);
    try {
      await cancel.mutateAsync();
      setNotice("Your cancellation has been recorded.");
    } catch (error) {
      setActionError(error);
    }
  };

  const changePlan = async (productCode: string) => {
    setActionError(null);
    setNotice(null);
    try {
      await change.mutateAsync(productCode);
      setNotice("Your plan change is scheduled for the start of your next billing period.");
    } catch (error) {
      setActionError(error);
    }
  };

  const actionFor = (group: PlanGroup, product: Product): ReactNode => {
    if (subscription === null) {
      return (
        <Button
          className="w-full"
          disabled={busy}
          onClick={() => {
            void checkout.start("subscription", product.code);
          }}
        >
          Subscribe to {group.name}
        </Button>
      );
    }
    if (subscription.product.code === product.code) {
      return (
        <Button className="w-full" variant="outline" disabled>
          Current plan
        </Button>
      );
    }
    if (subscription.pendingProduct?.code === product.code) {
      return (
        <Button className="w-full" variant="outline" disabled>
          Scheduled for next cycle
        </Button>
      );
    }
    if (!isChangeable(subscription)) {
      return null;
    }
    return (
      <ConfirmDialog
        title={`Switch to ${product.name}?`}
        description={
          subscription.currentPeriodEnd
            ? `Your plan changes to ${product.name} on ${formatDate(subscription.currentPeriodEnd)}, at the start of your next billing period. Until then you keep ${subscription.product.name} and its credits.`
            : `Your plan changes to ${product.name} at the start of your next billing period.`
        }
        confirmLabel="Switch plan"
        trigger={
          <Button className="w-full" variant="outline">
            Switch from next cycle
          </Button>
        }
        onConfirm={() => changePlan(product.code)}
      />
    );
  };

  return (
    <div className="space-y-8">
      <div aria-live="polite" className="space-y-2 empty:hidden">
        {notice ? <p className="text-sm text-success">{notice}</p> : null}
      </div>
      {actionError ? <BillingError error={actionError} /> : null}
      {checkout.error ? <BillingError error={checkout.error} /> : null}
      {unavailable ? (
        <p role="alert" className="text-sm text-destructive">
          That plan is no longer available. Choose one of the plans below.
        </p>
      ) : null}
      {subscription && requestedPlan ? (
        <p role="note" className="text-sm text-subtle-foreground">
          You already have a subscription, so you can switch plans from your next billing period
          instead of starting a new one.
        </p>
      ) : null}
      <CheckoutHost checkout={checkout} />
      {checkout.starting ? (
        <p role="status" className="text-sm text-muted-foreground">
          Preparing your subscription…
        </p>
      ) : null}
      {subscription ? (
        <SubscriptionCard
          subscription={subscription}
          actions={
            subscription.cancelAtPeriodEnd ? null : (
              <ConfirmDialog
                title="Cancel your subscription?"
                description={cancelDescription(subscription)}
                confirmLabel="Cancel subscription"
                cancelLabel="Keep subscription"
                destructive
                trigger={<Button variant="outline">Cancel subscription</Button>}
                onConfirm={cancelSubscription}
              />
            )
          }
        />
      ) : null}
      <section aria-labelledby="plans-title" className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <h2 id="plans-title" className="text-xl font-semibold">
            {subscription ? "Change plan" : "Choose a plan"}
          </h2>
          <IntervalToggle value={interval} onChange={setChosenInterval} intervals={intervals} />
        </div>
        <p className="text-sm text-muted-foreground">
          Prices include GST. Plan changes apply from your next billing cycle, and subscription
          credits expire at the end of each billing period.
        </p>
        {groups.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Subscriptions are not available right now. Please check back soon.
          </p>
        ) : (
          <ul className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {groups.map((group) => {
              const product = group.byInterval[interval];
              return (
                <li key={group.planKey}>
                  <PlanCard
                    group={group}
                    interval={interval}
                    action={product ? actionFor(group, product) : null}
                  />
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
