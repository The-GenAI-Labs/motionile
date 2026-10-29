"use client";

import { useRouter } from "next/navigation";
import { useRef } from "react";

import { LazyVideoPlayer } from "@/features/library/components/lazy-video-player";
import type { Rendition, SharedVideo } from "@/features/library/types/library.types";

const MAX_LINK_REFRESHES = 2;

export const sharedRendition = (slug: string, video: SharedVideo): Rendition => ({
  id: `shared-${slug}`,
  aspect: video.aspect,
  width: video.width,
  height: video.height,
  durationMs: video.durationMs,
  status: "ready",
  burnedInSubtitles: false,
  url: video.playbackUrl,
  posterUrl: video.posterUrl,
});

interface SharedVideoPlayerProps {
  slug: string;
  video: SharedVideo;
}

export function SharedVideoPlayer({ slug, video }: SharedVideoPlayerProps) {
  const router = useRouter();
  const refreshes = useRef(0);
  return (
    <LazyVideoPlayer
      renditions={[sharedRendition(slug, video)]}
      deliveryMode="presigned"
      title={video.title}
      onPlaybackError={() => {
        if (refreshes.current < MAX_LINK_REFRESHES) {
          refreshes.current += 1;
          router.refresh();
        }
      }}
    />
  );
}
