"use client";

import { MicIcon, RotateCcwIcon, SquareIcon } from "lucide-react";
import { type ReactNode, useEffect, useId } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { LevelMeter } from "@/features/voices/components/level-meter";
import {
  type RecordedClip,
  type RecorderStatus,
  useAudioRecorder,
} from "@/features/voices/hooks/use-audio-recorder";
import { AUDIO_ACCEPT } from "@/features/voices/schemas/voices.schema";
import { formatClockMs } from "@/lib/utils/format";

interface AudioRecorderProps {
  subject: string;
  minMs: number;
  maxMs: number;
  clip: RecordedClip | null;
  onClipChange: (clip: RecordedClip | null) => void;
  disabled?: boolean;
  onUploadFile?: (file: File) => void;
  children?: ReactNode;
}

const MS_PER_SECOND = 1_000;

const announcement = (status: RecorderStatus, clip: RecordedClip | null): string => {
  if (status === "requesting") {
    return "Waiting for microphone permission.";
  }
  if (status === "recording") {
    return "Recording started.";
  }
  if (clip !== null) {
    return `Recording stopped. It is ${formatClockMs(clip.durationMs)} long.`;
  }
  return "";
};

const seconds = (milliseconds: number): string => String(Math.round(milliseconds / MS_PER_SECOND));

export function AudioRecorder({
  subject,
  minMs,
  maxMs,
  clip,
  onClipChange,
  disabled = false,
  onUploadFile,
  children,
}: AudioRecorderProps) {
  const fileId = useId();
  const recorder = useAudioRecorder({ maxMs, onComplete: onClipChange });
  const playbackUrl = clip?.url ?? null;

  useEffect(
    () => () => {
      if (playbackUrl !== null) {
        URL.revokeObjectURL(playbackUrl);
      }
    },
    [playbackUrl],
  );
  const recording = recorder.status === "recording";
  const busy = recorder.status === "requesting";
  const unavailable =
    !recorder.supported || recorder.status === "denied" || recorder.status === "error";
  const tooShort = clip !== null && clip.durationMs < minMs;

  return (
    <div className="space-y-4">
      <p role="status" aria-live="polite" className="sr-only">
        {announcement(recorder.status, clip)}
      </p>
      {unavailable ? (
        <div role="alert" className="space-y-2 rounded-lg border bg-surface p-4 text-sm">
          <p className="font-medium">
            {recorder.supported
              ? recorder.status === "denied"
                ? "Microphone access was blocked."
                : "The microphone could not be started."
              : "Recording is not supported in this browser."}
          </p>
          <p className="text-muted-foreground">
            {recorder.status === "denied"
              ? "Allow microphone access for this site in your browser settings and try again, or upload a recording instead."
              : "Upload an audio file of the same recording instead."}
          </p>
        </div>
      ) : null}
      {recorder.supported ? (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            {recording ? (
              <Button type="button" variant="destructive" onClick={recorder.stop}>
                <SquareIcon aria-hidden="true" /> Stop recording
              </Button>
            ) : (
              <Button
                type="button"
                disabled={disabled || busy}
                aria-busy={busy}
                onClick={() => {
                  onClipChange(null);
                  void recorder.start();
                }}
              >
                {clip === null ? (
                  <MicIcon aria-hidden="true" />
                ) : (
                  <RotateCcwIcon aria-hidden="true" />
                )}
                {clip === null ? "Start recording" : "Record again"}
              </Button>
            )}
            <span role="timer" aria-label="Recording length" className="font-mono text-sm">
              {formatClockMs(recording ? recorder.elapsedMs : (clip?.durationMs ?? 0))}
              <span className="text-muted-foreground">{` / ${formatClockMs(maxMs)} max`}</span>
            </span>
          </div>
          <LevelMeter level={recording ? recorder.level : 0} />
          <p className="text-xs text-muted-foreground">
            {`Record between ${seconds(minMs)} and ${seconds(maxMs)} seconds for the ${subject}.`}
          </p>
        </div>
      ) : null}
      {onUploadFile !== undefined && unavailable ? (
        <div className="space-y-2">
          <Label htmlFor={fileId}>{`Upload an audio file for the ${subject}`}</Label>
          <Input
            id={fileId}
            type="file"
            accept={AUDIO_ACCEPT}
            disabled={disabled}
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) {
                onUploadFile(file);
              }
              event.target.value = "";
            }}
          />
        </div>
      ) : null}
      {clip !== null && playbackUrl !== null ? (
        <div className="space-y-3">
          <audio
            controls
            src={playbackUrl}
            aria-label={`Playback of your ${subject} recording`}
            className="w-full focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none"
          />
          {tooShort ? (
            <p role="alert" className="text-sm text-destructive">
              {`The recording is too short. Record at least ${seconds(minMs)} seconds.`}
            </p>
          ) : (
            children
          )}
        </div>
      ) : null}
    </div>
  );
}
