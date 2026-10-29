import { PlayIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { LibraryThumbnail } from "@/features/library/components/library-thumbnail";
import { VideoActions } from "@/features/library/components/video-actions";
import { fallbackNotice } from "@/features/library/schemas/library.schema";
import type { LibraryItem } from "@/features/library/types/library.types";
import { formatDate, formatDurationMs } from "@/lib/utils/format";

interface LibraryCardProps {
  item: LibraryItem;
  onOpen: (jobId: string) => void;
}

export function LibraryCard({ item, onOpen }: LibraryCardProps) {
  const fallbackCount = item.fallbackSceneIds.length;
  return (
    <article className="flex h-full flex-col overflow-hidden rounded-xl border bg-surface">
      <button
        type="button"
        aria-label={`Play ${item.title}`}
        onClick={() => {
          onOpen(item.jobId);
        }}
        className="group relative aspect-video w-full overflow-hidden bg-elevated focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none focus-visible:ring-inset"
      >
        <LibraryThumbnail url={item.thumbnailUrl} />
        <span
          aria-hidden="true"
          className="absolute inset-0 grid place-items-center bg-background/0 opacity-0 transition-opacity group-hover:bg-background/40 group-hover:opacity-100 group-focus-visible:opacity-100"
        >
          <PlayIcon className="size-8" />
        </span>
        {item.durationMs === null ? null : (
          <span className="absolute right-2 bottom-2 rounded-md bg-background/80 px-1.5 py-0.5 font-mono text-xs">
            {formatDurationMs(item.durationMs)}
          </span>
        )}
      </button>
      <div className="flex flex-1 flex-col gap-3 p-4">
        <div className="space-y-1">
          <h3 className="line-clamp-2 font-medium">{item.title}</h3>
          <p className="text-xs text-muted-foreground">
            Created {formatDate(item.completedAt ?? item.createdAt)}
          </p>
        </div>
        <ul aria-label="Details" className="flex flex-wrap gap-1">
          {item.aspects.map((aspect) => (
            <li key={aspect}>
              <Badge variant="outline" className="font-mono">
                {aspect}
              </Badge>
            </li>
          ))}
          {item.shareSlug === null ? null : (
            <li>
              <Badge variant="success">Shared</Badge>
            </li>
          )}
          {fallbackCount === 0 ? null : (
            <li>
              <Badge variant="outline" title={fallbackNotice(fallbackCount)}>
                {fallbackNotice(fallbackCount)}
              </Badge>
            </li>
          )}
        </ul>
        <div className="mt-auto">
          <VideoActions item={item} />
        </div>
      </div>
    </article>
  );
}
