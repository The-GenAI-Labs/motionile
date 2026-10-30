"use client";

import Link from "next/link";

import { Skeleton } from "@/components/ui/skeleton";
import { useWallet } from "@/features/credits/hooks/use-wallet";
import { generationErrorMessage } from "@/features/generation/errors";
import type { useJobEstimate } from "@/features/generation/hooks/use-job-estimate";
import { formatCredits } from "@/lib/utils/format";

interface EstimatePanelProps {
  estimate: ReturnType<typeof useJobEstimate>;
}

export function EstimatePanel({ estimate: result }: EstimatePanelProps) {
  const wallet = useWallet();
  const { estimate } = result;
  const balance = wallet.data?.available ?? estimate?.availableCredits ?? null;
  return (
    <section
      aria-labelledby="estimate-heading"
      className="space-y-3 rounded-xl border bg-surface p-5"
    >
      <h2 id="estimate-heading" className="text-lg font-semibold">
        Cost
      </h2>
      <div aria-live="polite" aria-busy={result.isSettling} className="space-y-2">
        {estimate === undefined && result.isPending ? <Skeleton className="h-10 w-full" /> : null}
        {result.isError ? (
          <p role="alert" className="text-sm text-destructive">
            {generationErrorMessage(result.error)}
          </p>
        ) : null}
        {estimate ? (
          <dl className="grid grid-cols-2 gap-y-1 text-sm">
            <dt className="text-subtle-foreground">This video</dt>
            <dd className="text-right font-mono">{formatCredits(estimate.credits)} credits</dd>
            <dt className="text-subtle-foreground">Your balance</dt>
            <dd className="text-right font-mono">
              {balance === null ? "Loading" : `${formatCredits(balance)} credits`}
            </dd>
          </dl>
        ) : null}
        {estimate?.clonedVoice ? (
          <p className="text-xs text-muted-foreground">Includes the cloned voice premium.</p>
        ) : null}
        {result.isSettling && estimate ? (
          <p className="text-xs text-muted-foreground">Updating the estimate</p>
        ) : null}
        {estimate ? (
          estimate.affordable ? (
            <p className="text-sm text-success">Your balance covers this video.</p>
          ) : (
            <p role="alert" className="text-sm text-destructive">
              You need {formatCredits(Math.max(0, estimate.credits - estimate.availableCredits))}{" "}
              more credits for this video.
            </p>
          )
        ) : null}
      </div>
      <p className="text-xs text-muted-foreground">
        Credits are held when you start and anything unused is returned.{" "}
        <Link href="/billing/credits" className="underline underline-offset-4">
          View credit packs
        </Link>
      </p>
    </section>
  );
}
