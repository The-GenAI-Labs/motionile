"use client";

import { BanIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { Button } from "@/components/ui/button";
import { adminRenderErrorMessage } from "@/features/admin-render/errors";
import { useCancelTestbedRender } from "@/features/admin-render/hooks/use-testbed";

export function CancelRenderButton({ renderId }: { renderId: string }) {
  const cancel = useCancelTestbedRender(renderId);
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
        <Button variant="outline">
          <BanIcon aria-hidden="true" /> Cancel render
        </Button>
      }
      title="Cancel this render?"
      description="The render stops at the next safe point. Work already done is discarded and cannot be resumed."
      confirmLabel="Cancel render"
      cancelLabel="Keep rendering"
      destructive
      error={failure === null ? null : adminRenderErrorMessage(failure)}
      onConfirm={async () => {
        setFailure(null);
        try {
          await cancel.mutateAsync();
        } catch (error) {
          setFailure(error);
          throw error;
        }
        toast.success("Cancellation requested");
      }}
    />
  );
}
