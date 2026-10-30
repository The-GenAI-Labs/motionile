"use client";

import { BanIcon, Trash2Icon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { Button } from "@/components/ui/button";
import { generationErrorMessage } from "@/features/generation/errors";
import { useCancelJob, useDeleteJob } from "@/features/generation/hooks/use-job-actions";
import type { Job } from "@/features/generation/types/generation.types";
import { formatCredits } from "@/lib/utils/format";

export function CancelJobButton({ job }: { job: Job }) {
  const cancel = useCancelJob(job.id);
  const [failure, setFailure] = useState<unknown>(null);
  return (
    <ConfirmDialog
      trigger={
        <Button type="button" variant="outline">
          <BanIcon aria-hidden="true" /> Cancel video
        </Button>
      }
      title="Cancel this video?"
      description={`Work stops at the next step and the ${formatCredits(job.creditsReserved)} credits held for this video are returned to your balance.`}
      confirmLabel="Cancel video"
      cancelLabel="Keep going"
      destructive
      error={failure === null ? null : generationErrorMessage(failure)}
      onOpenChange={(open) => {
        if (open) {
          setFailure(null);
        }
      }}
      onConfirm={async () => {
        setFailure(null);
        try {
          await cancel.mutateAsync();
        } catch (error) {
          setFailure(error);
          throw error;
        }
        toast.success("Video cancelled. Your credits were returned.");
      }}
    />
  );
}

export function DeleteJobButton({ job, title }: { job: Job; title: string }) {
  const router = useRouter();
  const remove = useDeleteJob(job.id);
  const [failure, setFailure] = useState<unknown>(null);
  return (
    <ConfirmDialog
      trigger={
        <Button type="button" variant="outline">
          <Trash2Icon aria-hidden="true" /> Delete
        </Button>
      }
      title="Delete this video?"
      description={`${title} and its public links are removed. This cannot be undone.`}
      confirmLabel="Delete video"
      destructive
      error={failure === null ? null : generationErrorMessage(failure)}
      onOpenChange={(open) => {
        if (open) {
          setFailure(null);
        }
      }}
      onConfirm={async () => {
        setFailure(null);
        try {
          await remove.mutateAsync();
        } catch (error) {
          setFailure(error);
          throw error;
        }
        toast.success("Video deleted");
        router.push("/library");
      }}
    />
  );
}
