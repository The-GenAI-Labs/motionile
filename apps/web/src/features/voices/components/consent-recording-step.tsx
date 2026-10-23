"use client";

import { Loader2Icon, UploadIcon } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { AudioRecorder } from "@/features/voices/components/audio-recorder";
import { voiceErrorMessage } from "@/features/voices/errors";
import type { RecordedClip } from "@/features/voices/hooks/use-audio-recorder";
import { useUploadConsentRecording } from "@/features/voices/hooks/use-clone-attempt";
import { useCloneWizardStore } from "@/features/voices/store/clone-wizard.store";
import type { CloneStart } from "@/features/voices/types/voices.types";
import { formatClockMs } from "@/lib/utils/format";

const MS_PER_SECOND = 1_000;

interface ConsentRecordingStepProps {
  start: CloneStart;
}

export function ConsentRecordingStep({ start }: ConsentRecordingStepProps) {
  const clip = useCloneWizardStore((state) => state.consentClip);
  const uploaded = useCloneWizardStore((state) => state.consentUploaded);
  const setClip = useCloneWizardStore((state) => state.setConsentClip);
  const setUploaded = useCloneWizardStore((state) => state.setConsentUploaded);
  const setStep = useCloneWizardStore((state) => state.setStep);
  const upload = useUploadConsentRecording(start.attemptId);
  const [failure, setFailure] = useState<unknown>(null);
  const [uploadedLength, setUploadedLength] = useState<number | null>(null);

  const send = async (file: Blob, filename: string) => {
    setFailure(null);
    try {
      const attempt = await upload.mutateAsync({ file, filename });
      setUploaded(true);
      setUploadedLength(attempt.consentRecording?.durationMs ?? null);
    } catch (error) {
      setFailure(error);
    }
  };

  const sendClip = (recorded: RecordedClip) => send(recorded.blob, recorded.filename);

  return (
    <div className="space-y-6">
      <section aria-labelledby="consent-sentence-heading" className="space-y-3">
        <h3 id="consent-sentence-heading" className="text-lg font-medium">
          Read this sentence aloud
        </h3>
        <p className="text-sm text-subtle-foreground">
          Say it clearly, in your own voice, exactly as written. It is different every time and
          proves the recording is yours.
        </p>
        <blockquote
          lang="en"
          className="rounded-xl border bg-surface p-6 text-2xl leading-snug font-semibold sm:text-3xl"
        >
          {start.consentSentence}
        </blockquote>
      </section>
      <AudioRecorder
        subject="consent sentence"
        minMs={start.limits.consentMinSeconds * MS_PER_SECOND}
        maxMs={start.limits.consentMaxSeconds * MS_PER_SECOND}
        clip={clip}
        onClipChange={setClip}
        disabled={upload.isPending}
        onUploadFile={(file) => {
          void send(file, file.name);
        }}
      >
        {clip === null ? null : (
          <Button
            type="button"
            disabled={upload.isPending}
            aria-busy={upload.isPending}
            onClick={() => {
              void sendClip(clip);
            }}
          >
            {upload.isPending ? (
              <Loader2Icon aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
            ) : (
              <UploadIcon aria-hidden="true" />
            )}
            Upload this recording
          </Button>
        )}
      </AudioRecorder>
      <p role="status" aria-live="polite" className="text-sm text-success">
        {upload.isPending
          ? "Uploading the consent recording."
          : uploaded
            ? `Consent recording uploaded${uploadedLength === null ? "" : ` (${formatClockMs(uploadedLength)})`}.`
            : ""}
      </p>
      {failure === null ? null : (
        <p role="alert" className="text-sm text-destructive">
          {voiceErrorMessage(failure)}
        </p>
      )}
      <div className="flex flex-wrap gap-3">
        <Button
          type="button"
          disabled={!uploaded || upload.isPending}
          onClick={() => {
            setStep("samples");
          }}
        >
          Continue to voice samples
        </Button>
      </div>
    </div>
  );
}
