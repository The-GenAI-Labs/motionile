"use client";

import { CheckCircle2Icon, Loader2Icon, TriangleAlertIcon } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { voiceErrorMessage, voiceFailureMessage } from "@/features/voices/errors";
import { useVoice } from "@/features/voices/hooks/use-voices";
import { useCloneWizardStore } from "@/features/voices/store/clone-wizard.store";

interface StatusStepProps {
  voiceId: string;
}

const galleryLink = (
  <Button asChild variant="outline">
    <Link href={{ pathname: "/settings/voices" }}>Back to your voices</Link>
  </Button>
);

export function StatusStep({ voiceId }: StatusStepProps) {
  const voice = useVoice(voiceId);
  const reset = useCloneWizardStore((state) => state.reset);

  if (voice.isError) {
    return (
      <div className="space-y-4">
        <p role="alert" className="text-sm text-destructive">
          {voiceErrorMessage(voice.error)}
        </p>
        <div className="flex flex-wrap gap-3">
          <Button
            variant="outline"
            onClick={() => {
              void voice.refetch();
            }}
          >
            Try again
          </Button>
          {galleryLink}
        </div>
      </div>
    );
  }
  if (voice.data?.status === "ready") {
    return (
      <div className="space-y-4">
        <p role="status" className="flex items-center gap-2 text-lg font-medium text-success">
          <CheckCircle2Icon aria-hidden="true" className="size-5" />
          {`${voice.data.name} is ready to use.`}
        </p>
        <p className="text-sm text-subtle-foreground">
          Pick it when you create a video, or set it as your default voice from your voices page.
        </p>
        {galleryLink}
      </div>
    );
  }
  if (voice.data?.status === "failed") {
    return (
      <div className="space-y-4">
        <p role="alert" className="flex items-start gap-2 text-destructive">
          <TriangleAlertIcon aria-hidden="true" className="mt-0.5 size-5 shrink-0" />
          <span>
            <span className="block font-medium">Your voice could not be created.</span>
            <span className="block text-sm">{voiceFailureMessage(voice.data.failureCode)}</span>
          </span>
        </p>
        <div className="flex flex-wrap gap-3">
          <Button onClick={reset}>Start again</Button>
          {galleryLink}
        </div>
      </div>
    );
  }
  return (
    <div className="space-y-4">
      <p role="status" aria-live="polite" className="flex items-center gap-2 text-lg font-medium">
        <Loader2Icon
          aria-hidden="true"
          className="size-5 animate-spin motion-reduce:animate-none"
        />
        Creating your voice. This usually takes a minute or two.
      </p>
      <p className="text-sm text-subtle-foreground">
        We are checking your consent recording and training the voice. You can leave this page; the
        voice will appear in your list when it is ready.
      </p>
      {galleryLink}
    </div>
  );
}
