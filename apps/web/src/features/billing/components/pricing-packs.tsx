import { CheckoutLink } from "@/features/billing/components/checkout-link";
import { PackCard } from "@/features/billing/components/pack-card";
import { packCheckoutPath } from "@/features/billing/plan-groups";
import type { Product } from "@/features/billing/types/billing.types";

interface PricingPacksProps {
  packs: readonly Product[];
}

export function PricingPacks({ packs }: PricingPacksProps) {
  if (packs.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        Credit packs are not available right now. Please check back soon.
      </p>
    );
  }
  return (
    <ul className="grid gap-4 md:grid-cols-3">
      {packs.map((pack) => (
        <li key={pack.code}>
          <PackCard
            pack={pack}
            action={
              <CheckoutLink path={packCheckoutPath(pack.code)} variant="outline">
                Buy {pack.name}
              </CheckoutLink>
            }
          />
        </li>
      ))}
    </ul>
  );
}
