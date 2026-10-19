"use client";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { BillingError } from "@/features/billing/components/billing-error";
import { CheckoutHost } from "@/features/billing/components/checkout-host";
import { PackCard } from "@/features/billing/components/pack-card";
import { useAutoStartCheckout } from "@/features/billing/hooks/use-auto-start-checkout";
import { useCheckout } from "@/features/billing/hooks/use-checkout";
import { useProducts } from "@/features/billing/hooks/use-products";

interface CreditPackStoreProps {
  requestedPack?: string | null;
  cleanPath?: string;
}

export function CreditPackStore({
  requestedPack = null,
  cleanPath = "/billing/credits",
}: CreditPackStoreProps) {
  const products = useProducts();
  const checkout = useCheckout();
  const packs = products.data?.creditPacks;
  const { unavailable } = useAutoStartCheckout({
    kind: "credit_pack",
    requestedCode: requestedPack,
    products: packs,
    ready: true,
    checkout,
    cleanPath,
  });
  const busy = checkout.starting || checkout.target !== null;

  if (products.isPending) {
    return (
      <div className="grid gap-4 md:grid-cols-3" role="status" aria-label="Loading credit packs">
        <Skeleton className="h-72" />
        <Skeleton className="h-72" />
        <Skeleton className="h-72" />
      </div>
    );
  }
  if (products.isError) {
    return (
      <BillingError
        error={products.error}
        onRetry={() => {
          void products.refetch();
        }}
      />
    );
  }

  return (
    <div className="space-y-6">
      {unavailable ? (
        <p role="alert" className="text-sm text-destructive">
          That credit pack is no longer available. Choose one of the packs below.
        </p>
      ) : null}
      {checkout.error ? <BillingError error={checkout.error} /> : null}
      <CheckoutHost checkout={checkout} />
      {checkout.starting ? (
        <p role="status" className="text-sm text-muted-foreground">
          Preparing your order…
        </p>
      ) : null}
      {products.data.creditPacks.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Credit packs are not available right now. Please check back soon.
        </p>
      ) : (
        <ul className="grid gap-4 md:grid-cols-3">
          {products.data.creditPacks.map((pack) => (
            <li key={pack.code}>
              <PackCard
                pack={pack}
                action={
                  <Button
                    className="w-full"
                    disabled={busy}
                    onClick={() => {
                      void checkout.start("credit_pack", pack.code);
                    }}
                  >
                    Buy {pack.name}
                  </Button>
                }
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
