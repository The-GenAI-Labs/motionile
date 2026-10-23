"use client";

import { Trash2Icon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { Button } from "@/components/ui/button";
import { voiceErrorMessage } from "@/features/voices/errors";
import { useDeleteVoice } from "@/features/voices/hooks/use-voices";
import type { Voice } from "@/features/voices/types/voices.types";

export function DeleteVoiceButton({ voice }: { voice: Voice }) {
  const remove = useDeleteVoice();
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
        <Button variant="outline" size="sm" aria-label={`Delete ${voice.name}`}>
          <Trash2Icon aria-hidden="true" /> Delete
        </Button>
      }
      title={`Delete ${voice.name}?`}
      description="The voice is deleted at the provider and its recordings are removed. Videos you already made keep their audio. This cannot be undone."
      confirmLabel="Delete voice"
      destructive
      error={failure === null ? null : voiceErrorMessage(failure)}
      onConfirm={async () => {
        setFailure(null);
        try {
          await remove.mutateAsync(voice.id);
        } catch (error) {
          setFailure(error);
          throw error;
        }
        toast.success(`Deleted ${voice.name}`);
      }}
    />
  );
}
