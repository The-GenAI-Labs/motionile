"use client";

import { Trash2Icon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { Button } from "@/components/ui/button";
import { libraryErrorMessage } from "@/features/library/errors";
import { useDeleteVideo } from "@/features/library/hooks/use-library";
import type { LibraryItem } from "@/features/library/types/library.types";

export function DeleteVideoDialog({ item }: { item: LibraryItem }) {
  const remove = useDeleteVideo();
  const [open, setOpen] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
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
        <Button variant="outline" size="sm" aria-label={`Delete ${item.title}`}>
          <Trash2Icon aria-hidden="true" /> Delete
        </Button>
      }
      title="Delete this video?"
      description={`${item.title} and its public links are removed from your library. This cannot be undone.`}
      confirmLabel="Delete video"
      destructive
      error={failure === null ? null : libraryErrorMessage(failure)}
      onConfirm={async () => {
        setFailure(null);
        try {
          await remove.mutateAsync(item.jobId);
        } catch (error) {
          setFailure(error);
          throw error;
        }
        toast.success("Video deleted");
      }}
    />
  );
}
