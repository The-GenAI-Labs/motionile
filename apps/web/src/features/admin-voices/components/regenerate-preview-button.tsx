"use client";

import { Loader2Icon, RefreshCwIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { adminVoiceErrorMessage } from "@/features/admin-voices/errors";
import { useRegenerateVoicePreview } from "@/features/admin-voices/hooks/use-admin-voices";
import type { AdminVoice } from "@/features/admin-voices/types/admin-voices.types";

export function RegeneratePreviewButton({ voice }: { voice: AdminVoice }) {
  const regenerate = useRegenerateVoicePreview(voice.id);
  const [failure, setFailure] = useState<unknown>(null);
  return (
    <div className="flex flex-col gap-1">
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={regenerate.isPending}
        aria-busy={regenerate.isPending}
        aria-label={`Regenerate preview of ${voice.name}`}
        onClick={() => {
          setFailure(null);
          regenerate
            .mutateAsync()
            .then(() => toast.success(`Preview of ${voice.name} regenerated`))
            .catch((error: unknown) => {
              setFailure(error);
            });
        }}
      >
        {regenerate.isPending ? (
          <Loader2Icon aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
        ) : (
          <RefreshCwIcon aria-hidden="true" />
        )}
        Regenerate preview
      </Button>
      {failure === null ? null : (
        <p role="alert" className="max-w-56 text-xs text-destructive">
          {adminVoiceErrorMessage(failure)}
        </p>
      )}
    </div>
  );
}
