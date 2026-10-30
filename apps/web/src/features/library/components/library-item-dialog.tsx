"use client";

import { useQueryClient } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { LibraryPlayer } from "@/features/library/components/library-player";
import { VideoActions } from "@/features/library/components/video-actions";
import { libraryKeys } from "@/features/library/query-keys";
import { fallbackNotice } from "@/features/library/schemas/library.schema";
import type { LibraryItem } from "@/features/library/types/library.types";
import { formatDateTime, formatDurationMs } from "@/lib/utils/format";

interface LibraryItemDialogProps {
  item: LibraryItem | undefined;
  onClose: () => void;
}

export function LibraryItemDialog({ item, onClose }: LibraryItemDialogProps) {
  const client = useQueryClient();
  return (
    <Dialog
      open={item !== undefined}
      onOpenChange={(open) => {
        if (!open) {
          onClose();
        }
      }}
    >
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-3xl">
        {item === undefined ? null : (
          <>
            <DialogHeader>
              <DialogTitle>{item.title}</DialogTitle>
              <DialogDescription>{item.query}</DialogDescription>
            </DialogHeader>
            <LibraryPlayer
              item={item}
              onRefreshRenditions={() => {
                void client.invalidateQueries({ queryKey: libraryKeys.lists() });
              }}
            />
            <dl className="grid gap-3 text-sm sm:grid-cols-3">
              <div>
                <dt className="text-muted-foreground">Length</dt>
                <dd className="font-mono">
                  {item.durationMs === null ? "Unknown" : formatDurationMs(item.durationMs)}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Finished</dt>
                <dd>{formatDateTime(item.completedAt ?? item.createdAt)}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Versions</dt>
                <dd className="font-mono">{item.aspects.join(", ")}</dd>
              </div>
            </dl>
            {item.fallbackSceneIds.length === 0 ? null : (
              <p role="note" className="flex items-center gap-2 text-sm text-subtle-foreground">
                <Badge variant="outline">Notice</Badge>
                {fallbackNotice(item.fallbackSceneIds.length)} because the full animation could not
                be checked. You can revise the video to try again.
              </p>
            )}
            <VideoActions item={item} />
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
