"use client";

import { DownloadIcon } from "lucide-react";

import { useRenditions } from "@/features/library/hooks/use-renditions";
import {
  aspectDescriptions,
  aspectLabels,
  playableRenditions,
} from "@/features/library/schemas/library.schema";

export function Downloads({ renderId }: { renderId: string }) {
  const renditions = useRenditions(renderId);
  const ready = playableRenditions(renditions.data ?? []);
  if (renditions.isError) {
    return (
      <p role="alert" className="text-sm text-destructive">
        The download links could not be loaded.
      </p>
    );
  }
  if (ready.length === 0) {
    return null;
  }
  return (
    <section aria-labelledby="downloads-heading" className="space-y-3">
      <h3 id="downloads-heading" className="text-lg font-semibold">
        Downloads
      </h3>
      <ul aria-label="Downloads" className="space-y-2">
        {ready.map((rendition) => {
          const label = `${aspectLabels[rendition.aspect]} ${aspectDescriptions[rendition.aspect].toLowerCase()}`;
          return (
            <li
              key={rendition.id}
              className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border bg-surface px-3 py-2 text-sm"
            >
              <a
                href={rendition.url}
                download
                rel="noopener"
                aria-label={`Download ${label} video`}
                className="inline-flex items-center gap-2 rounded-sm font-medium underline-offset-4 outline-none hover:underline focus-visible:ring-[3px] focus-visible:ring-ring"
              >
                <DownloadIcon aria-hidden="true" className="size-4" />
                {label}
              </a>
              {rendition.subtitlesUrl ? (
                <a
                  href={rendition.subtitlesUrl}
                  download
                  rel="noopener"
                  aria-label={`Download ${label} subtitles as VTT`}
                  className="rounded-sm text-subtle-foreground underline underline-offset-4 outline-none focus-visible:ring-[3px] focus-visible:ring-ring"
                >
                  Subtitles (VTT)
                </a>
              ) : null}
              {rendition.subtitlesSrtUrl ? (
                <a
                  href={rendition.subtitlesSrtUrl}
                  download
                  rel="noopener"
                  aria-label={`Download ${label} subtitles as SRT`}
                  className="rounded-sm text-subtle-foreground underline underline-offset-4 outline-none focus-visible:ring-[3px] focus-visible:ring-ring"
                >
                  Subtitles (SRT)
                </a>
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
