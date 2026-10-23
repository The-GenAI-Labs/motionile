"use client";

import { TriangleAlertIcon, VideoOffIcon } from "lucide-react";
import { useRef, useState } from "react";

import { EmptyState } from "@/components/shared/empty-state";
import { LoadingSpinner } from "@/components/shared/loading-spinner";
import { Button } from "@/components/ui/button";
import { AspectSwitcher } from "@/features/library/components/aspect-switcher";
import { MusicCredit } from "@/features/library/components/music-credit";
import { isHttpsUrl, playableRenditions } from "@/features/library/schemas/library.schema";
import type {
  Aspect,
  MediaDeliveryMode,
  PlayableRendition,
  Rendition,
} from "@/features/library/types/library.types";
import { cn } from "@/lib/utils/cn";

type PlaybackStatus = "loading" | "ready" | "error";

interface Resume {
  time: number;
  play: boolean;
}

const frameClasses = {
  "16:9": "aspect-video w-full",
  "9:16": "mx-auto aspect-9/16 w-full max-w-sm",
  "1:1": "mx-auto aspect-square w-full max-w-xl",
} as const satisfies Record<Aspect, string>;

const HAVE_NOTHING = 0;

export interface VideoPlayerProps {
  renditions: readonly Rendition[];
  deliveryMode: MediaDeliveryMode;
  title: string;
  initialAspect?: Aspect;
  onPlaybackError?: () => void;
  className?: string;
}

const pickRendition = (
  options: readonly PlayableRendition[],
  selected: Aspect | undefined,
  initial: Aspect | undefined,
): PlayableRendition | undefined =>
  options.find((option) => option.aspect === selected) ??
  options.find((option) => option.aspect === initial) ??
  options[0];

export function VideoPlayer({
  renditions,
  deliveryMode,
  title,
  initialAspect,
  onPlaybackError,
  className,
}: VideoPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const resumeRef = useRef<Resume>({ time: 0, play: false });
  const [displayed, setDisplayed] = useState(renditions);
  const [playing, setPlaying] = useState(false);
  const [selected, setSelected] = useState<Aspect | undefined>(initialAspect);
  const [status, setStatus] = useState<PlaybackStatus>("loading");

  if (renditions !== displayed && !playing) {
    setDisplayed(renditions);
  }

  const options = playableRenditions(displayed);
  const active = pickRendition(options, selected, initialAspect);

  if (active === undefined) {
    return (
      <EmptyState
        icon={VideoOffIcon}
        title="No playable video yet"
        description="This render has no finished video. Check back once rendering completes."
        headingLevel={3}
        {...(className ? { className } : {})}
      />
    );
  }

  const captureResume = (): void => {
    const video = videoRef.current;
    if (video) {
      resumeRef.current = { time: video.currentTime, play: !video.paused && !video.ended };
    }
  };

  const switchAspect = (aspect: Aspect): void => {
    if (aspect === active.aspect) {
      return;
    }
    captureResume();
    setDisplayed(renditions);
    setPlaying(false);
    setStatus("loading");
    setSelected(aspect);
  };

  const handleLoadedMetadata = (): void => {
    const video = videoRef.current;
    if (video) {
      const { time, play } = resumeRef.current;
      if (time > 0) {
        video.currentTime = Number.isFinite(video.duration) ? Math.min(time, video.duration) : time;
      }
      if (play) {
        video.play().catch(() => undefined);
      }
      resumeRef.current = { time: 0, play: false };
    }
    setStatus("ready");
  };

  const handleTimeUpdate = (): void => {
    const video = videoRef.current;
    if (video && video.readyState > HAVE_NOTHING) {
      resumeRef.current = { ...resumeRef.current, time: video.currentTime };
    }
  };

  const handleError = (): void => {
    captureResume();
    setDisplayed(renditions);
    setPlaying(false);
    setStatus("error");
    onPlaybackError?.();
  };

  const retry = (): void => {
    setDisplayed(renditions);
    setStatus("loading");
    videoRef.current?.load();
  };

  const captions =
    active.subtitlesUrl && !active.burnedInSubtitles ? (
      <track key={active.subtitlesUrl} kind="captions" label="Captions" src={active.subtitlesUrl} />
    ) : null;
  const poster = active.posterUrl ?? active.posterJpegUrl ?? undefined;
  const attribution = active.attribution;

  return (
    <section aria-label={title} className={cn("space-y-3", className)}>
      <div
        className={cn(
          "relative overflow-hidden rounded-xl border bg-background",
          frameClasses[active.aspect],
        )}
      >
        <video
          key={active.id}
          ref={videoRef}
          src={active.url}
          poster={poster}
          controls
          playsInline
          preload="metadata"
          crossOrigin={deliveryMode === "cloudfront" ? "use-credentials" : "anonymous"}
          aria-label={title}
          className="size-full bg-background object-contain focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none"
          onLoadStart={() => {
            setStatus("loading");
          }}
          onLoadedMetadata={handleLoadedMetadata}
          onTimeUpdate={handleTimeUpdate}
          onSeeked={handleTimeUpdate}
          onPlay={() => {
            setPlaying(true);
          }}
          onPause={() => {
            setPlaying(false);
          }}
          onEnded={() => {
            setPlaying(false);
          }}
          onError={handleError}
        >
          {captions}
          Your browser cannot play this video.
        </video>
        {status === "loading" ? (
          <div className="pointer-events-none absolute inset-0 grid place-items-center">
            <LoadingSpinner label="Loading video" showLabel />
          </div>
        ) : null}
        {status === "error" ? (
          <div
            role="alert"
            className="absolute inset-0 grid place-items-center overflow-auto bg-surface p-4"
          >
            <EmptyState
              icon={TriangleAlertIcon}
              title="This video could not be played"
              description="Check your connection and try again. If it keeps failing, reload the page to renew your viewing session."
              headingLevel={3}
              className="border-none"
              action={
                <Button variant="outline" onClick={retry}>
                  Try again
                </Button>
              }
            />
          </div>
        ) : null}
      </div>
      {options.length > 1 ? (
        <AspectSwitcher
          aspects={options.map((option) => option.aspect)}
          value={active.aspect}
          onChange={switchAspect}
        />
      ) : null}
      {attribution ? (
        <MusicCredit
          title={attribution.title}
          licenseName={attribution.licenseName}
          licenseUrl={isHttpsUrl(attribution.licenseUrl) ? attribution.licenseUrl : null}
          attributionText={attribution.attributionText ?? null}
        />
      ) : null}
    </section>
  );
}
