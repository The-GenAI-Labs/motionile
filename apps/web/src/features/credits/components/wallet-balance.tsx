"use client";

import { Skeleton } from "@/components/ui/skeleton";
import { BillingError } from "@/features/billing/components/billing-error";
import { WalletSummary } from "@/features/credits/components/wallet-summary";
import { useWallet } from "@/features/credits/hooks/use-wallet";

export function WalletBalance() {
  const wallet = useWallet();
  if (wallet.isPending) {
    return <Skeleton role="status" aria-label="Loading credits" className="h-56" />;
  }
  if (wallet.isError) {
    return (
      <BillingError
        error={wallet.error}
        onRetry={() => {
          void wallet.refetch();
        }}
      />
    );
  }
  return <WalletSummary wallet={wallet.data} />;
}
