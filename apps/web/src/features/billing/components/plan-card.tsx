import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { type BillingInterval, intervalNouns } from "@/features/billing/plan-groups";
import type { PlanGroup } from "@/features/billing/types/billing.types";
import { formatCredits, formatPaise } from "@/lib/utils/format";

interface PlanCardProps {
  group: PlanGroup;
  interval: BillingInterval;
  action?: ReactNode;
  badge?: string;
}

export function PlanCard({ group, interval, action, badge }: PlanCardProps) {
  const product = group.byInterval[interval];
  const headingId = `plan-${group.planKey}`;
  return (
    <article
      aria-labelledby={headingId}
      className="flex h-full flex-col gap-4 rounded-xl border bg-surface p-6"
    >
      <div className="flex min-h-7 items-center justify-between gap-2">
        <h3 id={headingId} className="text-xl font-semibold">
          {group.name}
        </h3>
        {badge ? <Badge variant="outline">{badge}</Badge> : null}
      </div>
      {product ? (
        <>
          <div>
            <p className="flex items-baseline gap-1">
              <span className="font-mono text-3xl font-semibold">
                {formatPaise(product.pricePaise)}
              </span>
              <span className="text-sm text-muted-foreground">per {intervalNouns[interval]}</span>
            </p>
            <p className="mt-1 text-xs text-muted-foreground">incl. GST</p>
          </div>
          <p className="text-sm text-subtle-foreground">
            {formatCredits(product.creditsGranted)} credits every {intervalNouns[interval]}
          </p>
          {product.description ? (
            <p className="text-sm text-muted-foreground">{product.description}</p>
          ) : null}
          <ul className="flex flex-1 list-disc flex-col gap-1 pl-5 text-sm text-subtle-foreground">
            {product.features.map((feature) => (
              <li key={feature}>{feature}</li>
            ))}
          </ul>
          {action ? <div>{action}</div> : null}
        </>
      ) : (
        <p className="flex-1 text-sm text-muted-foreground">
          This plan is not offered with {intervalNouns[interval]}ly billing.
        </p>
      )}
    </article>
  );
}
