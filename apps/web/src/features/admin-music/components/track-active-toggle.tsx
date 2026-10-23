"use client";

import { PauseIcon, PlayIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { Button } from "@/components/ui/button";
import { adminMusicErrorMessage } from "@/features/admin-music/errors";
import { useSetMusicTrackActive } from "@/features/admin-music/hooks/use-music-tracks";
import type { MusicTrack } from "@/features/admin-music/types/admin-music.types";

export function TrackActiveToggle({ track }: { track: MusicTrack }) {
  const mutation = useSetMusicTrackActive(track.id);
  const [open, setOpen] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  const deactivating = track.isActive;
  const action = deactivating ? "deactivate" : "activate";
  const Icon = deactivating ? PauseIcon : PlayIcon;
  const verb = deactivating ? "Deactivate" : "Activate";
  return (
    <ConfirmDialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) {
          setFailure(null);
        }
      }}
      trigger={
        <Button variant="outline" size="sm" aria-label={`${verb} ${track.title}`}>
          <Icon aria-hidden="true" /> {verb}
        </Button>
      }
      title={`${verb} this track?`}
      description={
        deactivating
          ? `${track.title} stops being offered for new renders. Videos already rendered keep their mixed audio.`
          : `${track.title} becomes selectable for new renders.`
      }
      confirmLabel={verb}
      destructive={deactivating}
      error={failure === null ? null : adminMusicErrorMessage(failure)}
      onConfirm={async () => {
        setFailure(null);
        try {
          await mutation.mutateAsync(action);
        } catch (error) {
          setFailure(error);
          throw error;
        }
        toast.success(`${track.title} is now ${deactivating ? "inactive" : "active"}`);
      }}
    />
  );
}
