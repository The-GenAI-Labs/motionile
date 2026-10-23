"use client";

import { DownloadIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { BedRendition } from "@/features/admin-render/types/admin-render.types";
import { RenderPlayer } from "@/features/library/components/render-player";

interface CompletedPanelProps {
  renderId: string;
  renditions: readonly BedRendition[];
}

const firstUrl = (
  renditions: readonly BedRendition[],
  pick: (rendition: BedRendition) => string | null | undefined,
): string | null => {
  for (const rendition of renditions) {
    const url = pick(rendition);
    if (url) {
      return url;
    }
  }
  return null;
};

export function CompletedPanel({ renderId, renditions }: CompletedPanelProps) {
  const vtt = firstUrl(renditions, (rendition) => rendition.subtitlesUrl);
  const srt = firstUrl(renditions, (rendition) => rendition.subtitlesSrtUrl);
  const posters = renditions.filter((rendition) => rendition.posterUrl ?? rendition.posterJpegUrl);
  return (
    <section aria-labelledby="result-heading" className="space-y-5">
      <h2 id="result-heading" className="text-xl font-semibold">
        Result
      </h2>
      <RenderPlayer renderId={renderId} title="Test bed render" />
      {posters.length > 0 ? (
        <ul aria-label="Posters" className="flex flex-wrap gap-3">
          {posters.map((rendition) => (
            <li key={rendition.id}>
              <Button asChild variant="outline" size="sm">
                <a
                  href={rendition.posterUrl ?? rendition.posterJpegUrl ?? ""}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {`Open poster frame for ${rendition.aspect}`}
                </a>
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
      {vtt === null && srt === null ? (
        <p className="text-sm text-muted-foreground">This render has no subtitle files.</p>
      ) : (
        <div className="flex flex-wrap gap-3">
          {vtt === null ? null : (
            <Button asChild variant="outline">
              <a href={vtt} download="subtitles.vtt" rel="noopener noreferrer">
                <DownloadIcon aria-hidden="true" /> Download WebVTT subtitles
              </a>
            </Button>
          )}
          {srt === null ? null : (
            <Button asChild variant="outline">
              <a href={srt} download="subtitles.srt" rel="noopener noreferrer">
                <DownloadIcon aria-hidden="true" /> Download SRT subtitles
              </a>
            </Button>
          )}
        </div>
      )}
    </section>
  );
}
