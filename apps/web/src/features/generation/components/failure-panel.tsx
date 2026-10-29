import { CircleXIcon } from "lucide-react";
import type { Route } from "next";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { explainFailure } from "@/features/generation/errors";
import type { Job } from "@/features/generation/types/generation.types";
import { formatCredits } from "@/lib/utils/format";

export const retryHref = (job: Job): Route => {
  if (job.topicId !== null) {
    return `/create?topic=${job.topicId}` as Route;
  }
  return `/create?query=${encodeURIComponent(job.query)}` as Route;
};

export function FailurePanel({ job }: { job: Job }) {
  const status = job.status === "cancelled" ? "cancelled" : "failed";
  const returned = job.creditsReserved > 0 ? job.creditsReserved : job.creditsEstimated;
  const explanation = explainFailure(status, job.errorCode, job.errorTitle, job.errorMessage);
  return (
    <section
      aria-labelledby="failure-heading"
      className="space-y-4 rounded-xl border border-destructive bg-surface p-6"
    >
      <div className="flex items-start gap-3">
        <CircleXIcon aria-hidden="true" className="mt-1 size-5 shrink-0 text-destructive" />
        <div className="space-y-2">
          <h2 id="failure-heading" className="text-xl font-semibold">
            {explanation.title}
          </h2>
          <p className="text-sm text-subtle-foreground">{explanation.message}</p>
          <p className="text-sm">
            {returned > 0
              ? `${formatCredits(returned)} credits were held for this video and have been returned to your balance.`
              : "No credits were used for this video."}
          </p>
          {job.errorCode ? (
            <p className="font-mono text-xs text-muted-foreground">{`Code: ${job.errorCode}`}</p>
          ) : null}
        </div>
      </div>
      <Button asChild>
        <Link href={retryHref(job)}>Try again</Link>
      </Button>
    </section>
  );
}
