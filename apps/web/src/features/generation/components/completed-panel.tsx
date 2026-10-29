"use client";

import type { Route } from "next";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Downloads } from "@/features/generation/components/downloads";
import { FallbackNotices } from "@/features/generation/components/fallback-notices";
import { DeleteJobButton } from "@/features/generation/components/job-actions";
import { ReviseDialog } from "@/features/generation/components/revise-dialog";
import { useStoryboard } from "@/features/generation/hooks/use-storyboard";
import type { Job } from "@/features/generation/types/generation.types";
import { RenderPlayer } from "@/features/library/components/render-player";
import { ShareLinkDialog } from "@/features/library/components/share-link-dialog";
import { useRenditions } from "@/features/library/hooks/use-renditions";
import type { LibraryItem } from "@/features/library/types/library.types";
import { useFlag } from "@/features/platform/hooks/use-flags";
import { formatCredits } from "@/lib/utils/format";

export const PUBLISHING_FLAG = "publishing.enabled";

function PublishCallToAction({ job }: { job: Job }) {
  const enabled = useFlag(PUBLISHING_FLAG);
  if (!enabled) {
    return null;
  }
  return (
    <Button asChild>
      <Link href={`/publish?job=${job.id}` as Route}>Publish</Link>
    </Button>
  );
}

function ShareAction({ job, renderId, title }: { job: Job; renderId: string; title: string }) {
  const renditions = useRenditions(renderId);
  const item: LibraryItem = {
    aspects: job.options.aspects,
    completedAt: job.completedAt,
    createdAt: job.createdAt,
    durationMs:
      renditions.data?.find(
        (rendition) => rendition.durationMs !== null && rendition.durationMs !== undefined,
      )?.durationMs ?? null,
    fallbackSceneIds: job.fallbackSceneIds,
    jobId: job.id,
    query: job.query,
    renditions: renditions.data ?? [],
    shareSlug: null,
    thumbnailUrl: null,
    title,
  };
  return <ShareLinkDialog item={item} />;
}

export function CompletedPanel({ job }: { job: Job }) {
  const storyboard = useStoryboard(job.id, true);
  const title = storyboard.data?.content.title ?? job.query;
  return (
    <div className="space-y-8">
      <section aria-labelledby="player-heading" className="space-y-3">
        <h2 id="player-heading" className="text-xl font-semibold">
          Your video
        </h2>
        {job.renderId === null ? (
          <p role="status" className="text-sm text-muted-foreground">
            The video file is being prepared.
          </p>
        ) : (
          <RenderPlayer renderId={job.renderId} title={title} />
        )}
        {job.creditsCharged === null ? null : (
          <p className="font-mono text-xs text-muted-foreground">
            {`${formatCredits(job.creditsCharged)} credits charged`}
            {job.creditsReserved > job.creditsCharged
              ? `, ${formatCredits(job.creditsReserved - job.creditsCharged)} returned`
              : ""}
          </p>
        )}
      </section>
      <FallbackNotices job={job} />
      {job.renderId === null ? null : <Downloads renderId={job.renderId} />}
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Video actions">
        {job.renderId === null ? null : (
          <ShareAction job={job} renderId={job.renderId} title={title} />
        )}
        <ReviseDialog job={job} />
        <DeleteJobButton job={job} title={title} />
        <PublishCallToAction job={job} />
      </div>
    </div>
  );
}
