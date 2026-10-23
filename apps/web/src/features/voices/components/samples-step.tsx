"use client";

import { Loader2Icon, PlusIcon, Trash2Icon, XIcon } from "lucide-react";
import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { AudioRecorder } from "@/features/voices/components/audio-recorder";
import { voiceErrorMessage } from "@/features/voices/errors";
import type { RecordedClip } from "@/features/voices/hooks/use-audio-recorder";
import {
  useAddCloneSample,
  useCloneAttempt,
  useRemoveCloneSample,
} from "@/features/voices/hooks/use-clone-attempt";
import { AUDIO_ACCEPT } from "@/features/voices/schemas/voices.schema";
import { useCloneWizardStore } from "@/features/voices/store/clone-wizard.store";
import type { CloneStart } from "@/features/voices/types/voices.types";
import { formatClockMs } from "@/lib/utils/format";

const MS_PER_SECOND = 1_000;
const SAMPLE_RECORDING_MIN_MS = 3_000;

interface SamplesStepProps {
  start: CloneStart;
}

export function SamplesStep({ start }: SamplesStepProps) {
  const fileId = useId();
  const attempt = useCloneAttempt(start.attemptId);
  const addSample = useAddCloneSample(start.attemptId);
  const removeSample = useRemoveCloneSample(start.attemptId);
  const uploads = useCloneWizardStore((state) => state.uploads);
  const addUpload = useCloneWizardStore((state) => state.addUpload);
  const updateUpload = useCloneWizardStore((state) => state.updateUpload);
  const removeUpload = useCloneWizardStore((state) => state.removeUpload);
  const setStep = useCloneWizardStore((state) => state.setStep);
  const [clip, setClip] = useState<RecordedClip | null>(null);
  const [removeFailure, setRemoveFailure] = useState<unknown>(null);
  const [announcement, setAnnouncement] = useState("");

  const { limits } = start;
  const samples = attempt.data?.samples ?? [];
  const totalMs = attempt.data?.totalSampleMs ?? 0;
  const minMs = limits.sampleMinTotalSeconds * MS_PER_SECOND;
  const maxMs = limits.sampleMaxTotalSeconds * MS_PER_SECOND;
  const uploading = uploads.some((upload) => upload.status === "uploading");
  const enough = totalMs >= minMs && totalMs <= maxMs;
  const percent = Math.min(100, Math.round((totalMs / minMs) * 100));

  const uploadOne = async (file: Blob, filename: string): Promise<void> => {
    const id = crypto.randomUUID();
    addUpload({ id, name: filename, status: "uploading", message: null });
    setAnnouncement(`Uploading ${filename}.`);
    try {
      await addSample.mutateAsync({ file, filename });
      removeUpload(id);
      setAnnouncement(`${filename} was added.`);
    } catch (error) {
      updateUpload(id, { status: "failed", message: voiceErrorMessage(error) });
      setAnnouncement(`${filename} could not be added.`);
    }
  };

  const uploadMany = async (files: readonly File[]): Promise<void> => {
    for (const file of files) {
      await uploadOne(file, file.name);
    }
  };

  const remove = async (sampleId: string): Promise<void> => {
    setRemoveFailure(null);
    try {
      await removeSample.mutateAsync(sampleId);
    } catch (error) {
      setRemoveFailure(error);
    }
  };

  return (
    <div className="space-y-8">
      <section aria-labelledby="samples-progress-heading" className="space-y-3">
        <h3 id="samples-progress-heading" className="text-lg font-medium">
          Voice samples
        </h3>
        <p className="text-sm text-subtle-foreground">
          {`Add ${formatClockMs(minMs)} to ${formatClockMs(maxMs)} of clear, continuous speech from a quiet room, with no music or other voices. Record it here or upload audio files.`}
        </p>
        <div
          role="progressbar"
          aria-label="Sample length collected"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percent}
          aria-valuetext={`${formatClockMs(totalMs)} collected of at least ${formatClockMs(minMs)}`}
          className="h-2 w-full overflow-hidden rounded-full bg-elevated"
        >
          <div
            aria-hidden="true"
            className="h-full bg-success transition-[width] motion-reduce:transition-none"
            style={{ width: `${String(percent)}%` }}
          />
        </div>
        <p className="font-mono text-sm">
          {`${formatClockMs(totalMs)} of ${formatClockMs(minMs)} minimum, ${formatClockMs(maxMs)} maximum`}
        </p>
        {totalMs > maxMs ? (
          <p role="alert" className="text-sm text-destructive">
            {`The samples are longer than ${formatClockMs(maxMs)}. Remove a file to continue.`}
          </p>
        ) : null}
      </section>

      <section aria-labelledby="samples-record-heading" className="space-y-4">
        <h3 id="samples-record-heading" className="text-lg font-medium">
          Record a sample
        </h3>
        <AudioRecorder
          subject="voice sample"
          minMs={SAMPLE_RECORDING_MIN_MS}
          maxMs={maxMs}
          clip={clip}
          onClipChange={setClip}
          disabled={uploading}
        >
          {clip === null ? null : (
            <Button
              type="button"
              disabled={uploading}
              onClick={() => {
                const current = clip;
                setClip(null);
                void uploadOne(current.blob, current.filename);
              }}
            >
              <PlusIcon aria-hidden="true" /> Add this recording as a sample
            </Button>
          )}
        </AudioRecorder>
      </section>

      <section aria-labelledby="samples-upload-heading" className="space-y-3">
        <h3 id="samples-upload-heading" className="text-lg font-medium">
          Upload audio files
        </h3>
        <div className="space-y-2">
          <Label htmlFor={fileId}>Upload voice sample files</Label>
          <Input
            id={fileId}
            type="file"
            multiple
            accept={AUDIO_ACCEPT}
            onChange={(event) => {
              const files = [...(event.target.files ?? [])];
              event.target.value = "";
              void uploadMany(files);
            }}
          />
          <p className="text-xs text-muted-foreground">
            {`Up to ${String(limits.maxSampleFiles)} files, each up to ${String(Math.round(limits.sampleMaxBytes / (1024 * 1024)))} MB.`}
          </p>
        </div>
      </section>

      <section aria-labelledby="samples-list-heading" className="space-y-3">
        <h3 id="samples-list-heading" className="text-lg font-medium">
          Added samples
        </h3>
        <p role="status" aria-live="polite" className="sr-only">
          {announcement}
        </p>
        {samples.length === 0 && uploads.length === 0 ? (
          <p className="text-sm text-muted-foreground">No samples added yet.</p>
        ) : (
          <ul aria-label="Added samples" className="divide-y rounded-lg border">
            {samples.map((sample, index) => (
              <li key={sample.id} className="flex items-center justify-between gap-3 px-4 py-3">
                <span className="text-sm">
                  {`Sample ${String(index + 1)}`}
                  <span className="ml-3 font-mono text-muted-foreground">
                    {formatClockMs(sample.durationMs)}
                  </span>
                </span>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={removeSample.isPending}
                  aria-label={`Remove sample ${String(index + 1)}`}
                  onClick={() => {
                    void remove(sample.id);
                  }}
                >
                  <Trash2Icon aria-hidden="true" /> Remove
                </Button>
              </li>
            ))}
            {uploads.map((upload) => (
              <li key={upload.id} className="flex items-center justify-between gap-3 px-4 py-3">
                <span className="text-sm">
                  <span className="font-mono">{upload.name}</span>
                  {upload.status === "uploading" ? (
                    <span className="ml-3 inline-flex items-center gap-2 text-muted-foreground">
                      <Loader2Icon
                        aria-hidden="true"
                        className="size-4 animate-spin motion-reduce:animate-none"
                      />
                      Uploading
                    </span>
                  ) : (
                    <span role="alert" className="mt-1 block text-destructive">
                      {upload.message}
                    </span>
                  )}
                </span>
                {upload.status === "failed" ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    aria-label={`Dismiss the error for ${upload.name}`}
                    onClick={() => {
                      removeUpload(upload.id);
                    }}
                  >
                    <XIcon aria-hidden="true" /> Dismiss
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
        )}
        {removeFailure === null ? null : (
          <p role="alert" className="text-sm text-destructive">
            {voiceErrorMessage(removeFailure)}
          </p>
        )}
        {attempt.isError ? (
          <p role="alert" className="text-sm text-destructive">
            {voiceErrorMessage(attempt.error)}
          </p>
        ) : null}
      </section>

      <div className="flex flex-wrap gap-3">
        <Button
          type="button"
          variant="outline"
          onClick={() => {
            setStep("recording");
          }}
        >
          Back
        </Button>
        <Button
          type="button"
          disabled={!enough || uploading}
          onClick={() => {
            setStep("details");
          }}
        >
          Continue to name and language
        </Button>
      </div>
    </div>
  );
}
