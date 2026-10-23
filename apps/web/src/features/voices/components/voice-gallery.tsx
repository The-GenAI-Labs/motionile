"use client";

import { MicIcon, StarIcon } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/shared/empty-state";
import { LoadingSpinner } from "@/components/shared/loading-spinner";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import { DeleteVoiceButton } from "@/features/voices/components/delete-voice-button";
import { VoiceCard } from "@/features/voices/components/voice-card";
import { voiceErrorMessage } from "@/features/voices/errors";
import { useDefaultVoice } from "@/features/voices/hooks/use-default-voice";
import { useVoicePreviewPlayer } from "@/features/voices/hooks/use-voice-preview-player";
import { useAllVoices } from "@/features/voices/hooks/use-voices";
import { languageLabel } from "@/features/voices/schemas/voices.schema";
import type { Voice } from "@/features/voices/types/voices.types";

const uniqueLanguages = (voices: readonly Voice[]): string[] =>
  [...new Set(voices.map((voice) => voice.language))].toSorted();

const previewAnnouncement = (status: string, voice: Voice | undefined): string => {
  if (voice === undefined) {
    return "";
  }
  if (status === "loading") {
    return `Loading preview of ${voice.name}.`;
  }
  if (status === "playing") {
    return `Playing preview of ${voice.name}.`;
  }
  return status === "paused" ? `Paused preview of ${voice.name}.` : "";
};

export function VoiceGallery() {
  const voices = useAllVoices({});
  const defaults = useDefaultVoice();
  const player = useVoicePreviewPlayer();
  const [language, setLanguage] = useState("");
  const [failure, setFailure] = useState<unknown>(null);

  const builtin = voices.voices.filter((voice) => voice.kind === "builtin");
  const cloned = voices.voices.filter((voice) => voice.kind === "cloned");
  const visibleBuiltin = builtin.filter((voice) => language === "" || voice.language === language);
  const defaultVoice = voices.voices.find((voice) => voice.id === defaults.defaultVoiceId);
  const playing = voices.voices.find((voice) => voice.id === player.state.voiceId);

  const choose = async (voice: Voice | null) => {
    setFailure(null);
    try {
      await defaults.setDefaultVoice(voice?.id ?? null);
      toast.success(
        voice === null ? "Default voice cleared" : `${voice.name} is now your default voice`,
      );
    } catch (error) {
      setFailure(error);
    }
  };

  const defaultButton = (voice: Voice) =>
    voice.status === "ready" ? (
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={!defaults.isReady || defaults.isUpdating || voice.id === defaults.defaultVoiceId}
        aria-label={
          voice.id === defaults.defaultVoiceId
            ? `${voice.name} is your default voice`
            : `Set ${voice.name} as default`
        }
        onClick={() => {
          void choose(voice);
        }}
      >
        <StarIcon aria-hidden="true" />
        {voice.id === defaults.defaultVoiceId ? "Default" : "Set as default"}
      </Button>
    ) : null;

  if (voices.isPending) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-64" />
        <LoadingSpinner label="Loading voices" />
      </div>
    );
  }
  if (voices.isError) {
    return (
      <div role="alert" className="flex flex-wrap items-center gap-3 text-sm text-destructive">
        <p>{voiceErrorMessage(voices.error)}</p>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            void voices.refetch();
          }}
        >
          Try again
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-10">
      <audio {...player.audioProps} className="hidden" />
      <p role="status" aria-live="polite" className="sr-only">
        {previewAnnouncement(player.state.status, playing)}
      </p>

      <section aria-labelledby="default-voice-heading" className="space-y-3">
        <h2 id="default-voice-heading" className="text-xl font-semibold">
          Default voice
        </h2>
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-sm text-subtle-foreground">
            {defaultVoice === undefined
              ? "No default voice. You choose a voice each time you create a video."
              : `Your default voice is ${defaultVoice.name}.`}
          </p>
          {defaultVoice === undefined ? null : (
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={defaults.isUpdating}
              onClick={() => {
                void choose(null);
              }}
            >
              Clear default voice
            </Button>
          )}
        </div>
        {failure === null ? null : (
          <p role="alert" className="text-sm text-destructive">
            {voiceErrorMessage(failure)}
          </p>
        )}
      </section>

      <section aria-labelledby="builtin-voices-heading" className="space-y-4">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <h2 id="builtin-voices-heading" className="text-xl font-semibold">
            Built-in voices
          </h2>
          <div className="w-48 space-y-1">
            <Label htmlFor="voice-language">Language</Label>
            <NativeSelect
              id="voice-language"
              value={language}
              onChange={(event) => {
                setLanguage(event.target.value);
              }}
            >
              <option value="">All languages</option>
              {uniqueLanguages(builtin).map((code) => (
                <option key={code} value={code}>
                  {languageLabel(code)}
                </option>
              ))}
            </NativeSelect>
          </div>
        </div>
        {visibleBuiltin.length === 0 ? (
          <EmptyState
            headingLevel={3}
            title="No built-in voices"
            description="No voices match this language yet."
          />
        ) : (
          <ul aria-label="Built-in voices" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {visibleBuiltin.map((voice) => (
              <VoiceCard
                key={voice.id}
                voice={voice}
                isDefault={voice.id === defaults.defaultVoiceId}
                preview={player.state}
                onTogglePreview={(target) => {
                  void player.toggle(target);
                }}
              >
                {defaultButton(voice)}
              </VoiceCard>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="cloned-voices-heading" className="space-y-4">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <h2 id="cloned-voices-heading" className="text-xl font-semibold">
            Your cloned voices
          </h2>
          <Button asChild>
            <Link href={{ pathname: "/settings/voices/new" }}>
              <MicIcon aria-hidden="true" /> Clone your voice
            </Link>
          </Button>
        </div>
        {cloned.length === 0 ? (
          <EmptyState
            headingLevel={3}
            title="No cloned voices yet"
            description="Record a short consent sentence and a few minutes of speech to create a voice that sounds like you."
          />
        ) : (
          <ul aria-label="Your cloned voices" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {cloned.map((voice) => (
              <VoiceCard
                key={voice.id}
                voice={voice}
                isDefault={voice.id === defaults.defaultVoiceId}
                preview={player.state}
                onTogglePreview={(target) => {
                  void player.toggle(target);
                }}
              >
                {defaultButton(voice)}
                <DeleteVoiceButton voice={voice} />
              </VoiceCard>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
