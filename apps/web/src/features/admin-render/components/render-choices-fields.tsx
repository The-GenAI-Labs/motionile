"use client";

import { useFormContext, useWatch } from "react-hook-form";

import { Checkbox } from "@/components/ui/checkbox";
import {
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import { Switch } from "@/components/ui/switch";
import { useBedMusicTracks } from "@/features/admin-render/hooks/use-testbed";
import {
  aspectOptions,
  type ChoicesFormValues,
  MAX_FPS,
  MIN_FPS,
} from "@/features/admin-render/schemas/admin-render.schema";
import { useAllVoices } from "@/features/voices/hooks/use-voices";
import { formatDurationMs } from "@/lib/utils/format";

interface RenderChoicesFieldsProps {
  showVoice: boolean;
  idPrefix: string;
}

export function RenderChoicesFields({ showVoice, idPrefix }: RenderChoicesFieldsProps) {
  const form = useFormContext<ChoicesFormValues>();
  const voices = useAllVoices({});
  const music = useBedMusicTracks();
  const subtitles = useWatch({ control: form.control, name: "subtitles" });
  const readyVoices = voices.voices.filter((voice) => voice.status === "ready");

  return (
    <div className="grid gap-5 sm:grid-cols-2">
      {showVoice ? (
        <FormField
          control={form.control}
          name="voiceId"
          render={({ field }) => (
            <FormItem className="sm:col-span-2">
              <FormLabel>Voice</FormLabel>
              <FormControl>
                <NativeSelect {...field} disabled={voices.isPending}>
                  <option value="">{voices.isPending ? "Loading voices" : "Choose a voice"}</option>
                  {readyVoices.map((voice) => (
                    <option key={voice.id} value={voice.id}>
                      {`${voice.name} (${voice.language})`}
                    </option>
                  ))}
                </NativeSelect>
              </FormControl>
              {voices.isError ? (
                <p role="alert" className="text-sm text-destructive">
                  The voice list could not be loaded.
                </p>
              ) : null}
              <FormMessage />
            </FormItem>
          )}
        />
      ) : null}
      <FormField
        control={form.control}
        name="aspects"
        render={({ field }) => (
          <FormItem className="sm:col-span-2">
            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">Aspect ratios</legend>
              <div className="flex flex-wrap gap-4">
                {aspectOptions.map((option) => {
                  const id = `${idPrefix}-aspect-${option.value.replace(":", "x")}`;
                  return (
                    <div key={option.value} className="flex items-center gap-2">
                      <Checkbox
                        id={id}
                        checked={field.value.includes(option.value)}
                        onCheckedChange={(checked) => {
                          field.onChange(
                            checked === true
                              ? [...field.value, option.value]
                              : field.value.filter((aspect) => aspect !== option.value),
                          );
                        }}
                      />
                      <Label htmlFor={id}>{option.label}</Label>
                    </div>
                  );
                })}
              </div>
              <FormDescription>
                Choose from one to three. Each one is a separate video.
              </FormDescription>
            </fieldset>
            <FormMessage />
          </FormItem>
        )}
      />
      <FormField
        control={form.control}
        name="fps"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Frame rate (fps)</FormLabel>
            <FormControl>
              <Input
                type="number"
                inputMode="numeric"
                min={MIN_FPS}
                max={MAX_FPS}
                step={1}
                className="font-mono"
                {...field}
              />
            </FormControl>
            <FormDescription>{`From ${String(MIN_FPS)} to ${String(MAX_FPS)}.`}</FormDescription>
            <FormMessage />
          </FormItem>
        )}
      />
      <FormField
        control={form.control}
        name="musicTrackId"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Music track</FormLabel>
            <FormControl>
              <NativeSelect {...field}>
                <option value="">No music</option>
                {(music.data ?? []).map((track) => (
                  <option key={track.id} value={track.id}>
                    {`${track.title} (${track.mood}, ${formatDurationMs(track.durationMs)})`}
                  </option>
                ))}
              </NativeSelect>
            </FormControl>
            {music.isError ? (
              <p role="alert" className="text-sm text-destructive">
                The music list could not be loaded.
              </p>
            ) : null}
            <FormMessage />
          </FormItem>
        )}
      />
      <FormField
        control={form.control}
        name="subtitles"
        render={({ field }) => (
          <FormItem>
            <div className="flex items-center gap-3">
              <FormControl>
                <Switch
                  checked={field.value}
                  onCheckedChange={(checked) => {
                    field.onChange(checked);
                    if (!checked) {
                      form.setValue("burnInSubtitles", false);
                    }
                  }}
                />
              </FormControl>
              <FormLabel>Subtitles</FormLabel>
            </div>
            <FormDescription>Generate WebVTT and SRT files and a captions track.</FormDescription>
          </FormItem>
        )}
      />
      <FormField
        control={form.control}
        name="burnInSubtitles"
        render={({ field }) => (
          <FormItem>
            <div className="flex items-center gap-3">
              <FormControl>
                <Switch
                  checked={field.value && subtitles}
                  disabled={!subtitles}
                  onCheckedChange={field.onChange}
                />
              </FormControl>
              <FormLabel>Burn subtitles into the video</FormLabel>
            </div>
            <FormDescription>
              Needs subtitles. The captions become part of the picture.
            </FormDescription>
            <FormMessage />
          </FormItem>
        )}
      />
    </div>
  );
}
