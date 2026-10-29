"use client";

import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { LibraryThumbnail } from "@/features/library/components/library-thumbnail";
import { libraryErrorMessage } from "@/features/library/errors";
import { useActiveJobs, useRecentVideos } from "@/features/library/hooks/use-library";
import { jobPath, jobStatusLabels } from "@/features/library/schemas/library.schema";
import type { JobSummary, LibraryItem } from "@/features/library/types/library.types";
import { formatDurationMs } from "@/lib/utils/format";

const focusRing =
  "rounded-lg focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none";

function ActiveJobs({ jobs }: { jobs: readonly JobSummary[] }) {
  if (jobs.length === 0) {
    return null;
  }
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium text-subtle-foreground">In progress</h3>
      <ul aria-label="Videos in progress" className="space-y-2">
        {jobs.map((job) => (
          <li key={job.id}>
            <Link
              href={jobPath(job.id)}
              className={`flex items-center justify-between gap-3 border bg-background p-3 text-sm hover:bg-elevated ${focusRing}`}
            >
              <span className="min-w-0 truncate">{job.query}</span>
              <Badge variant="outline" className="shrink-0">
                {jobStatusLabels[job.status]}
              </Badge>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

function RecentTile({ item }: { item: LibraryItem }) {
  return (
    <li>
      <Link href={jobPath(item.jobId)} className={`block space-y-2 ${focusRing}`}>
        <span className="relative block aspect-video overflow-hidden rounded-lg border bg-elevated">
          <LibraryThumbnail url={item.thumbnailUrl} />
          {item.durationMs === null ? null : (
            <span className="absolute right-1 bottom-1 rounded bg-background/80 px-1 font-mono text-xs">
              {formatDurationMs(item.durationMs)}
            </span>
          )}
        </span>
        <span className="line-clamp-2 block text-sm font-medium">{item.title}</span>
      </Link>
    </li>
  );
}

export function RecentVideos() {
  const recent = useRecentVideos();
  const active = useActiveJobs();
  const activeJobs = active.data ?? [];
  const items = recent.data ?? [];
  return (
    <section
      aria-labelledby="recent-videos-heading"
      className="space-y-4 rounded-xl border bg-surface p-6"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="recent-videos-heading" className="font-semibold">
          Recent videos
        </h2>
        <Button asChild variant="link" size="sm">
          <Link href="/library">View library</Link>
        </Button>
      </div>
      <ActiveJobs jobs={activeJobs} />
      {recent.isPending ? (
        <Skeleton
          role="status"
          aria-hidden={false}
          aria-label="Loading recent videos"
          className="h-32"
        />
      ) : recent.isError ? (
        <div role="alert" className="flex flex-wrap items-center gap-3 text-sm text-destructive">
          <p>{libraryErrorMessage(recent.error)}</p>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              void recent.refetch();
            }}
          >
            Try again
          </Button>
        </div>
      ) : items.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Your finished videos will appear here.{" "}
          <Link href="/create" className={`underline underline-offset-4 ${focusRing}`}>
            Create your first video
          </Link>
          .
        </p>
      ) : (
        <ul aria-label="Recent videos" className="grid grid-cols-2 gap-4 sm:grid-cols-3">
          {items.map((item) => (
            <RecentTile key={item.jobId} item={item} />
          ))}
        </ul>
      )}
    </section>
  );
}
