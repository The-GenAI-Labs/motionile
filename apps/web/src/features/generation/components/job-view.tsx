"use client";

import Link from "next/link";

import { PageHeader } from "@/components/shared/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { POLL_INTERVAL_MS } from "@/features/generation/api/job-events.api";
import { CompletedPanel } from "@/features/generation/components/completed-panel";
import { FailurePanel } from "@/features/generation/components/failure-panel";
import { CancelJobButton } from "@/features/generation/components/job-actions";
import { StageTimeline } from "@/features/generation/components/stage-timeline";
import { StoryboardSection } from "@/features/generation/components/storyboard-section";
import { generationErrorMessage } from "@/features/generation/errors";
import { useJob } from "@/features/generation/hooks/use-job";
import { useJobEvents } from "@/features/generation/hooks/use-job-events";
import { isTerminalStatus } from "@/features/generation/schemas/generation.schema";
import { useJobConnection } from "@/features/generation/store/job-ui.store";
import type { Job } from "@/features/generation/types/generation.types";
import { jobStatusLabels } from "@/features/library/schemas/library.schema";
import { ApiError } from "@/lib/api/api-error";
import { formatCredits } from "@/lib/utils/format";

function JobSummary({ job }: { job: Job }) {
  return (
    <dl className="grid grid-cols-2 gap-x-6 gap-y-1 rounded-lg border bg-surface p-4 text-sm sm:grid-cols-4">
      <div>
        <dt className="text-xs text-muted-foreground">Length</dt>
        <dd className="font-mono">{`${String(job.options.durationSeconds)} s`}</dd>
      </div>
      <div>
        <dt className="text-xs text-muted-foreground">Aspect ratios</dt>
        <dd className="font-mono">{job.options.aspects.join(", ")}</dd>
      </div>
      <div>
        <dt className="text-xs text-muted-foreground">Style</dt>
        <dd>{job.options.style}</dd>
      </div>
      <div>
        <dt className="text-xs text-muted-foreground">Credits</dt>
        <dd className="font-mono">{formatCredits(job.creditsCharged ?? job.creditsReserved)}</dd>
      </div>
    </dl>
  );
}

function JobBody({ job }: { job: Job }) {
  if (job.status === "completed") {
    return (
      <>
        <CompletedPanel job={job} />
        <details className="rounded-lg border bg-surface p-4">
          <summary className="cursor-pointer text-sm font-medium outline-none focus-visible:ring-[3px] focus-visible:ring-ring">
            How this video was made
          </summary>
          <div className="mt-4">
            <StageTimeline job={job} />
          </div>
        </details>
      </>
    );
  }
  if (job.status === "failed" || job.status === "cancelled") {
    return (
      <>
        <FailurePanel job={job} />
        <StageTimeline job={job} />
      </>
    );
  }
  return (
    <>
      {job.status === "awaiting_approval" ? <StoryboardSection jobId={job.id} /> : null}
      <StageTimeline job={job} />
      <div className="flex flex-wrap items-center gap-3">
        <CancelJobButton job={job} />
        <p className="text-xs text-muted-foreground">
          Cancelling returns the credits held for this video.
        </p>
      </div>
    </>
  );
}

export function JobView({ jobId }: { jobId: string }) {
  const connection = useJobConnection(jobId);
  const query = useJob(jobId, { pollMs: connection === "polling" ? POLL_INTERVAL_MS : false });
  useJobEvents(jobId, { enabled: query.data !== undefined });
  const job = query.data;

  if (query.isPending) {
    return (
      <div role="status" aria-label="Loading the video" className="space-y-4">
        <Skeleton className="h-12 w-2/3" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }
  if (job === undefined) {
    const notFound = ApiError.from(query.error).status === 404;
    return (
      <div role="alert" className="space-y-3">
        <p className="text-destructive">{generationErrorMessage(query.error)}</p>
        {notFound ? (
          <Button asChild variant="outline">
            <Link href={"/library"}>Back to your library</Link>
          </Button>
        ) : (
          <Button
            variant="outline"
            onClick={() => {
              void query.refetch();
            }}
          >
            Try again
          </Button>
        )}
      </div>
    );
  }
  return (
    <div className="space-y-8">
      <PageHeader
        title={job.query}
        eyebrow="Video"
        description={
          <Badge variant="outline" aria-label={`Status: ${jobStatusLabels[job.status]}`}>
            {jobStatusLabels[job.status]}
          </Badge>
        }
        actions={
          isTerminalStatus(job.status) ? (
            <Button asChild variant="outline">
              <Link href={"/create"}>Create another</Link>
            </Button>
          ) : null
        }
      />
      <JobSummary job={job} />
      <JobBody job={job} />
    </div>
  );
}
