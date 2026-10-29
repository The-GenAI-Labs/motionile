"use client";

import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import { useAllVoices } from "@/features/voices/hooks/use-voices";

interface VoiceFieldProps {
  value: string | null;
  onChange: (voiceId: string | null) => void;
  clonedPremium: number | null;
}

export function VoiceField({ value, onChange, clonedPremium }: VoiceFieldProps) {
  const { voices, isPending, isError } = useAllVoices({});
  const ready = voices.filter((voice) => voice.status === "ready");
  const builtin = ready.filter((voice) => voice.kind === "builtin");
  const cloned = ready.filter((voice) => voice.kind === "cloned");
  const selected = ready.find((voice) => voice.id === value);
  return (
    <div className="space-y-2">
      <Label htmlFor="create-voice">Narration voice</Label>
      <NativeSelect
        id="create-voice"
        value={value ?? ""}
        disabled={isPending}
        onChange={(event) => {
          onChange(event.target.value === "" ? null : event.target.value);
        }}
      >
        <option value="">My default voice</option>
        {builtin.length > 0 ? (
          <optgroup label="Built-in voices">
            {builtin.map((voice) => (
              <option key={voice.id} value={voice.id}>
                {voice.name} ({voice.language})
              </option>
            ))}
          </optgroup>
        ) : null}
        {cloned.length > 0 ? (
          <optgroup label="Your cloned voices">
            {cloned.map((voice) => (
              <option key={voice.id} value={voice.id}>
                {voice.name} ({voice.language}) premium
              </option>
            ))}
          </optgroup>
        ) : null}
      </NativeSelect>
      {selected?.kind === "cloned" && clonedPremium !== null ? (
        <p className="text-xs text-muted-foreground">
          Cloned voices are premium and add {String(clonedPremium)} credits.
        </p>
      ) : null}
      {isError ? (
        <p role="alert" className="text-sm text-destructive">
          Voices could not be loaded. Your default voice will be used.
        </p>
      ) : null}
    </div>
  );
}
