"use client";

import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { BillingError } from "@/features/billing/components/billing-error";
import { CreditPackStore } from "@/features/billing/components/credit-pack-store";
import { SubscriptionCard } from "@/features/billing/components/subscription-card";
import { useSubscription } from "@/features/billing/hooks/use-subscription";
import { WalletBalance } from "@/features/credits/components/wallet-balance";

function PlanSection() {
  const subscription = useSubscription();
  if (subscription.isPending) {
    return <Skeleton role="status" aria-label="Loading plan" className="h-48" />;
  }
  if (subscription.isError) {
    return (
      <BillingError
        error={subscription.error}
        onRetry={() => {
          void subscription.refetch();
        }}
      />
    );
  }
  const current = subscription.data.subscription;
  if (current === null) {
    return (
      <section
        aria-labelledby="no-plan-title"
        className="space-y-3 rounded-xl border border-dashed p-6"
      >
        <h2 id="no-plan-title" className="font-semibold">
          No subscription
        </h2>
        <p className="text-sm text-muted-foreground">
          Subscribe for credits that renew every billing period, or buy a credit pack below.
        </p>
        <Button asChild variant="outline">
          <Link href="/billing/plans">See plans</Link>
        </Button>
      </section>
    );
  }
  return (
    <SubscriptionCard
      subscription={current}
      actions={
        <Button asChild variant="outline">
          <Link href="/billing/plans">Manage plan</Link>
        </Button>
      }
    />
  );
}

export function BillingOverview() {
  return (
    <div className="space-y-8">
      <div className="grid gap-4 lg:grid-cols-2">
        <WalletBalance />
        <PlanSection />
      </div>
      <section aria-labelledby="quick-buy-title" className="space-y-4">
        <h2 id="quick-buy-title" className="text-xl font-semibold">
          Buy credits
        </h2>
        <p className="text-sm text-muted-foreground">
          Credit packs are one-time payments, prices include GST, and the credits never expire.
        </p>
        <CreditPackStore cleanPath="/billing" />
      </section>
    </div>
  );
}
