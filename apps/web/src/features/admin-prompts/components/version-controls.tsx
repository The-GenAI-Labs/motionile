"use client";

import { RotateCcwIcon, ZapIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { Button } from "@/components/ui/button";
import { adminPromptsErrorMessage } from "@/features/admin-prompts/errors";
import {
  useActivatePromptVersion,
  useRollbackPromptTemplate,
} from "@/features/admin-prompts/hooks/use-admin-prompts";
import type { PromptVersion } from "@/features/admin-prompts/types/admin-prompts.types";

interface ActivateVersionProps {
  templateKey: string;
  version: PromptVersion;
}

export function ActivateVersionButton({ templateKey, version }: ActivateVersionProps) {
  const activate = useActivatePromptVersion(templateKey);
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
        <Button
          variant="outline"
          size="sm"
          disabled={version.isActive}
          aria-label={`Activate version ${String(version.version)}`}
        >
          <ZapIcon aria-hidden="true" /> Activate
        </Button>
      }
      title={`Activate version ${String(version.version)}?`}
      description={`New generations start using version ${String(version.version)} of ${templateKey}. It is only allowed when every required evaluation suite has a passing run that covers it.`}
      confirmLabel="Activate"
      error={failure === null ? null : adminPromptsErrorMessage(failure)}
      onConfirm={async () => {
        setFailure(null);
        try {
          await activate.mutateAsync(version.version);
        } catch (error) {
          setFailure(error);
          throw error;
        }
        toast.success(`Version ${String(version.version)} of ${templateKey} is now active`);
      }}
    />
  );
}

export function RollbackButton({
  templateKey,
  disabled,
}: {
  templateKey: string;
  disabled: boolean;
}) {
  const rollback = useRollbackPromptTemplate(templateKey);
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
        <Button variant="outline" disabled={disabled}>
          <RotateCcwIcon aria-hidden="true" /> Roll back
        </Button>
      }
      title={`Roll back ${templateKey}?`}
      description="The version that was active before the current one becomes active again."
      confirmLabel="Roll back"
      destructive
      error={failure === null ? null : adminPromptsErrorMessage(failure)}
      onConfirm={async () => {
        setFailure(null);
        try {
          const restored = await rollback.mutateAsync();
          toast.success(`Version ${String(restored.version)} of ${templateKey} is active again`);
        } catch (error) {
          setFailure(error);
          throw error;
        }
      }}
    />
  );
}
