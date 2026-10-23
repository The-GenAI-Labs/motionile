"use client";

import { TriangleAlertIcon } from "lucide-react";

import { LoadingSpinner } from "@/components/shared/loading-spinner";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { LazyVideoPlayer } from "@/features/library/components/lazy-video-player";
import { useMediaSession } from "@/features/library/hooks/use-media-session";
import { useRenditions } from "@/features/library/hooks/use-renditions";
import type { Aspect } from "@/features/library/types/library.types";

export interface RenderPlayerProps {
  renderId: string;
  title?: string;
  initialAspect?: Aspect;
  className?: string;
}

function PlayerError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div role="alert" className="flex flex-wrap items-center gap-3 text-sm text-destructive">
      <TriangleAlertIcon aria-hidden="true" className="size-4" />
      <p>{message}</p>
      <Button variant="outline" size="sm" onClick={onRetry}>
        Try again
      </Button>
    </div>
  );
}

export function RenderPlayer({
  renderId,
  title = "Video",
  initialAspect,
  className,
}: RenderPlayerProps) {
  const session = useMediaSession();
  const renditions = useRenditions(renderId);

  if (session.isError && session.mode === undefined) {
    return (
      <PlayerError
        message="Your viewing session could not be started."
        onRetry={() => {
          session.refresh().catch(() => undefined);
        }}
      />
    );
  }
  if (renditions.isError) {
    return (
      <PlayerError
        message="The video list could not be loaded."
        onRetry={() => {
          void renditions.refetch();
        }}
      />
    );
  }
  if (!session.isReady || renditions.data === undefined || session.mode === undefined) {
    return (
      <div className={className}>
        <Skeleton className="aspect-video w-full" />
        <LoadingSpinner label="Loading video" />
      </div>
    );
  }

  const recover = async (): Promise<void> => {
    if (session.mode === "cloudfront") {
      await session.refresh().catch(() => undefined);
    }
    await renditions.refetch();
  };

  return (
    <LazyVideoPlayer
      renditions={renditions.data}
      deliveryMode={session.mode}
      title={title}
      {...(initialAspect ? { initialAspect } : {})}
      {...(className ? { className } : {})}
      onPlaybackError={() => {
        void recover();
      }}
    />
  );
}
