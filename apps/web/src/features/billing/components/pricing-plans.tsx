"use client";

import { useState } from "react";

import { CheckoutLink } from "@/features/billing/components/checkout-link";
import { IntervalToggle } from "@/features/billing/components/interval-toggle";
import { PlanCard } from "@/features/billing/components/plan-card";
import {
  availableIntervals,
  type BillingInterval,
  groupPlans,
  planCheckoutPath,
} from "@/features/billing/plan-groups";
import type { Product } from "@/features/billing/types/billing.types";

interface PricingPlansProps {
  subscriptions: readonly Product[];
}

export function PricingPlans({ subscriptions }: PricingPlansProps) {
  const groups = groupPlans(subscriptions);
  const intervals = availableIntervals(groups);
  const [interval, setInterval] = useState<BillingInterval>(intervals[0] ?? "month");

  if (groups.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        Subscriptions are not available right now. Credit packs are available below.
      </p>
    );
  }

  return (
    <div className="space-y-6">
      {intervals.length > 1 ? (
        <IntervalToggle value={interval} onChange={setInterval} intervals={intervals} />
      ) : null}
      <ul className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {groups.map((group) => {
          const product = group.byInterval[interval];
          return (
            <li key={group.planKey}>
              <PlanCard
                group={group}
                interval={interval}
                action={
                  product ? (
                    <CheckoutLink path={planCheckoutPath(product.code)}>
                      Choose {group.name}
                    </CheckoutLink>
                  ) : null
                }
              />
            </li>
          );
        })}
      </ul>
    </div>
  );
}
