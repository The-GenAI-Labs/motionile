"use client";

import { TriangleAlertIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { LazyVideoPlayer } from "@/features/library/components/lazy-video-player";
import { useMediaSession } from "@/features/library/hooks/use-media-session";
import type { LibraryItem } from "@/features/library/types/library.types";

interface LibraryPlayerProps {
  item: LibraryItem;
  onRefreshRenditions: () => void;
}

export function LibraryPlayer({ item, onRefreshRenditions }: LibraryPlayerProps) {
  const session = useMediaSession();
  if (session.isError && session.mode === undefined) {
    return (
      <div role="alert" className="flex flex-wrap items-center gap-3 text-sm text-destructive">
        <TriangleAlertIcon aria-hidden="true" className="size-4" />
        <p>Your viewing session could not be started.</p>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            session.refresh().catch(() => undefined);
          }}
        >
          Try again
        </Button>
      </div>
    );
  }
  if (!session.isReady || session.mode === undefined) {
    return (
      <Skeleton
        role="status"
        aria-hidden={false}
        aria-label="Loading video"
        className="aspect-video w-full"
      />
    );
  }
  const mode = session.mode;
  return (
    <LazyVideoPlayer
      renditions={item.renditions}
      deliveryMode={mode}
      title={item.title}
      onPlaybackError={() => {
        if (mode === "cloudfront") {
          session.refresh().catch(() => undefined);
        }
        onRefreshRenditions();
      }}
    />
  );
}
