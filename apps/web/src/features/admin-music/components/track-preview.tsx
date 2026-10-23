"use client";

import { PlayIcon } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useRefreshMusicTracks } from "@/features/admin-music/hooks/use-refresh-music-tracks";
import type { MusicTrack } from "@/features/admin-music/types/admin-music.types";

export function TrackPreview({ track }: { track: MusicTrack }) {
  const [open, setOpen] = useState(false);
  const [failed, setFailed] = useState(false);
  const refresh = useRefreshMusicTracks();

  if (!track.previewUrl) {
    return <span className="text-sm text-muted-foreground">No preview</span>;
  }
  if (failed) {
    return (
      <div role="alert" className="flex items-center gap-2 text-sm text-destructive">
        <span>The preview link expired.</span>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            setFailed(false);
            setOpen(false);
            void refresh();
          }}
        >
          Refresh preview
        </Button>
      </div>
    );
  }
  if (!open) {
    return (
      <Button
        variant="outline"
        size="sm"
        aria-label={`Play preview of ${track.title}`}
        onClick={() => {
          setOpen(true);
        }}
      >
        <PlayIcon aria-hidden="true" /> Preview
      </Button>
    );
  }
  return (
    <audio
      controls
      autoPlay
      preload="none"
      src={track.previewUrl}
      aria-label={`Preview of ${track.title}`}
      className="h-9 w-56 max-w-full focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none"
      onError={() => {
        setFailed(true);
      }}
    />
  );
}
