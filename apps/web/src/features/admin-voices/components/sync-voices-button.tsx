"use client";

import { Loader2Icon, RefreshCwIcon } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { adminVoiceErrorMessage } from "@/features/admin-voices/errors";
import { useSyncVoices } from "@/features/admin-voices/hooks/use-admin-voices";

const plural = (count: number, one: string, many: string): string =>
  `${String(count)} ${count === 1 ? one : many}`;

export function SyncVoicesButton() {
  const sync = useSyncVoices();
  const [failure, setFailure] = useState<unknown>(null);
  return (
    <div className="flex flex-col items-end gap-2">
      <Button
        type="button"
        disabled={sync.isPending}
        aria-busy={sync.isPending}
        onClick={() => {
          setFailure(null);
          sync.mutateAsync().catch((error: unknown) => {
            setFailure(error);
          });
        }}
      >
        {sync.isPending ? (
          <Loader2Icon aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
        ) : (
          <RefreshCwIcon aria-hidden="true" />
        )}
        Sync from provider
      </Button>
      <div role="status" aria-live="polite" className="text-sm text-muted-foreground">
        {sync.isSuccess && failure === null
          ? `Sync finished: ${plural(sync.data.added, "voice added", "voices added")} (hidden until exposed), ${plural(sync.data.unchanged, "voice unchanged", "voices unchanged")}.`
          : null}
      </div>
      {failure === null ? null : (
        <p role="alert" className="max-w-sm text-right text-sm text-destructive">
          {adminVoiceErrorMessage(failure)}
        </p>
      )}
    </div>
  );
}
