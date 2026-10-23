"use client";

import { Loader2Icon, PauseIcon, PlayIcon } from "lucide-react";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { voiceFailureMessage } from "@/features/voices/errors";
import type { PreviewState, PreviewTarget } from "@/features/voices/hooks/use-voice-preview-player";
import { languageLabel } from "@/features/voices/schemas/voices.schema";
import type { Voice } from "@/features/voices/types/voices.types";

interface VoiceCardProps {
  voice: Voice;
  isDefault: boolean;
  preview: PreviewState;
  onTogglePreview: (target: PreviewTarget) => void;
  children?: ReactNode;
}

const statusLabels = {
  pending: "Creating",
  ready: "Ready",
  failed: "Failed",
  disabled: "Disabled",
} as const satisfies Record<Voice["status"], string>;

const statusVariants = {
  pending: "outline",
  ready: "success",
  failed: "destructive",
  disabled: "outline",
} as const satisfies Record<Voice["status"], "outline" | "success" | "destructive">;

export function PreviewButton({
  voice,
  preview,
  onTogglePreview,
}: Pick<VoiceCardProps, "voice" | "preview" | "onTogglePreview">) {
  const current = preview.voiceId === voice.id ? preview.status : "idle";
  if (!voice.hasPreview || voice.status !== "ready") {
    return null;
  }
  const loading = current === "loading";
  const playing = current === "playing";
  const label = loading
    ? `Loading preview of ${voice.name}`
    : playing
      ? `Pause preview of ${voice.name}`
      : `Play preview of ${voice.name}`;
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      aria-label={label}
      aria-busy={loading}
      disabled={loading}
      onClick={() => {
        onTogglePreview({ id: voice.id, name: voice.name });
      }}
    >
      {loading ? (
        <Loader2Icon aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
      ) : playing ? (
        <PauseIcon aria-hidden="true" />
      ) : (
        <PlayIcon aria-hidden="true" />
      )}
      {playing ? "Pause" : "Play"}
    </Button>
  );
}

export function VoiceCard({
  voice,
  isDefault,
  preview,
  onTogglePreview,
  children,
}: VoiceCardProps) {
  const previewError = preview.voiceId === voice.id && preview.status === "error";
  return (
    <li className="flex flex-col gap-3 rounded-xl border bg-surface p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate font-medium">{voice.name}</h3>
          <p className="text-sm text-muted-foreground">{languageLabel(voice.language)}</p>
        </div>
        <div className="flex shrink-0 flex-wrap justify-end gap-1">
          {isDefault ? <Badge variant="secondary">Default</Badge> : null}
          {voice.kind === "cloned" ? (
            <Badge variant={statusVariants[voice.status]}>{statusLabels[voice.status]}</Badge>
          ) : null}
        </div>
      </div>
      {voice.tags.length > 0 ? (
        <ul aria-label={`Tags for ${voice.name}`} className="flex flex-wrap gap-1">
          {voice.tags.map((tag) => (
            <li
              key={tag}
              className="rounded-full border px-2 py-0.5 text-xs text-subtle-foreground"
            >
              {tag}
            </li>
          ))}
        </ul>
      ) : null}
      {voice.status === "pending" ? (
        <p role="status" className="text-sm text-muted-foreground">
          Creating this voice. This page updates when it is ready.
        </p>
      ) : null}
      {voice.status === "failed" ? (
        <p role="alert" className="text-sm text-destructive">
          {voiceFailureMessage(voice.failureCode)}
        </p>
      ) : null}
      {previewError ? (
        <p role="alert" className="text-sm text-destructive">
          {preview.message}
        </p>
      ) : null}
      <div className="mt-auto flex flex-wrap gap-2">
        <PreviewButton voice={voice} preview={preview} onTogglePreview={onTogglePreview} />
        {children}
      </div>
    </li>
  );
}
