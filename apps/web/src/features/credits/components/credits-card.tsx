"use client";

import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { billingErrorMessage } from "@/features/billing/errors";
import { useWallet } from "@/features/credits/hooks/use-wallet";
import { formatCredits, formatDate } from "@/lib/utils/format";

export function CreditsCard() {
  const wallet = useWallet();
  const nextExpiry = wallet.data?.expiringSoon[0];
  return (
    <section aria-labelledby="credits-card-title" className="rounded-xl border bg-surface p-6">
      <h2 id="credits-card-title" className="font-semibold">
        Credits
      </h2>
      {wallet.isPending ? (
        <div role="status" aria-label="Loading credits" className="mt-3 space-y-2">
          <Skeleton className="h-9 w-24" />
          <Skeleton className="h-4 w-40" />
        </div>
      ) : wallet.isError ? (
        <div className="mt-3 space-y-3">
          <p role="alert" className="text-sm text-destructive">
            {billingErrorMessage(wallet.error)}
          </p>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              void wallet.refetch();
            }}
          >
            Try again
          </Button>
        </div>
      ) : (
        <div className="mt-3 space-y-3">
          <p>
            <span className="font-mono text-3xl font-semibold">
              {formatCredits(wallet.data.available)}
            </span>{" "}
            <span className="text-sm text-muted-foreground">credits available</span>
          </p>
          {wallet.data.reserved > 0 ? (
            <p className="text-sm text-muted-foreground">
              {formatCredits(wallet.data.reserved)} reserved for work in progress
            </p>
          ) : null}
          {nextExpiry ? (
            <p className="text-sm text-muted-foreground">
              {formatCredits(nextExpiry.remaining)} expire on {formatDate(nextExpiry.expiresAt)}
            </p>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Button asChild size="sm">
              <Link href="/billing/credits">Buy credits</Link>
            </Button>
            <Button asChild size="sm" variant="outline">
              <Link href="/billing">View billing</Link>
            </Button>
          </div>
        </div>
      )}
    </section>
  );
}
