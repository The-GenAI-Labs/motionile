import type { ReactNode } from "react";

import type { Product } from "@/features/billing/types/billing.types";
import { formatCredits, formatPaise } from "@/lib/utils/format";

interface PackCardProps {
  pack: Product;
  action?: ReactNode;
}

export function PackCard({ pack, action }: PackCardProps) {
  const headingId = `pack-${pack.code}`;
  return (
    <article
      aria-labelledby={headingId}
      className="flex h-full flex-col gap-4 rounded-xl border bg-surface p-6"
    >
      <h3 id={headingId} className="text-xl font-semibold">
        {pack.name}
      </h3>
      <div>
        <p className="font-mono text-3xl font-semibold">{formatPaise(pack.pricePaise)}</p>
        <p className="mt-1 text-xs text-muted-foreground">incl. GST, one-time payment</p>
      </div>
      <p className="text-sm text-subtle-foreground">
        {formatCredits(pack.creditsGranted)} credits that never expire
      </p>
      {pack.description ? (
        <p className="text-sm text-muted-foreground">{pack.description}</p>
      ) : null}
      <ul className="flex flex-1 list-disc flex-col gap-1 pl-5 text-sm text-subtle-foreground">
        {pack.features.map((feature) => (
          <li key={feature}>{feature}</li>
        ))}
      </ul>
      {action ? <div>{action}</div> : null}
    </article>
  );
}
