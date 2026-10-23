"use client";

import { useFormContext, useWatch } from "react-hook-form";

import {
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  MAX_SCENE_TEXT_CHARS,
  MAX_TOTAL_TEXT_CHARS,
  type RenderFormValues,
} from "@/features/admin-render/schemas/admin-render.schema";

interface NarrationFieldsProps {
  sceneIds: readonly string[];
}

const sceneTextName = (index: number) => `scenes.${String(index)}.text` as `scenes.${number}.text`;

const sceneAudioName = (index: number) =>
  `scenes.${String(index)}.audio` as `scenes.${number}.audio`;

const MODE_OPTIONS = [
  { value: "synthesize", label: "Synthesize speech" },
  { value: "upload", label: "Upload audio" },
] as const;

function CharacterCounter({ length, max }: { length: number; max: number }) {
  return (
    <p className="font-mono text-xs text-muted-foreground">
      {`${String(length)} / ${String(max)} characters`}
    </p>
  );
}

export function NarrationFields({ sceneIds }: NarrationFieldsProps) {
  const form = useFormContext<RenderFormValues>();
  const mode = useWatch({ control: form.control, name: "mode" });
  const scenes = useWatch({ control: form.control, name: "scenes" });
  const totalLength = scenes.reduce((sum, scene) => sum + scene.text.trim().length, 0);

  return (
    <div className="space-y-5">
      <FormField
        control={form.control}
        name="mode"
        render={({ field }) => (
          <FormItem>
            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">Narration source</legend>
              <div className="flex flex-wrap gap-5">
                {MODE_OPTIONS.map((option) => (
                  <label
                    key={option.value}
                    className="flex cursor-pointer items-center gap-2 text-sm"
                  >
                    <input
                      type="radio"
                      name={field.name}
                      value={option.value}
                      checked={field.value === option.value}
                      className="size-4 accent-primary focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none"
                      onChange={() => {
                        field.onChange(option.value);
                        form.clearErrors("scenes");
                      }}
                    />
                    {option.label}
                  </label>
                ))}
              </div>
            </fieldset>
          </FormItem>
        )}
      />
      {sceneIds.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Choose a composition to list its scenes. Each scene gets its own narration.
        </p>
      ) : (
        <ol aria-label="Scene narration" className="space-y-5">
          {sceneIds.map((sceneId, index) => (
            <li key={sceneId} className="space-y-3 rounded-lg border bg-surface p-4">
              <p className="font-mono text-sm font-medium">{`Scene ${sceneId}`}</p>
              {mode === "synthesize" ? (
                <FormField
                  control={form.control}
                  name={sceneTextName(index)}
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>{`Narration for scene ${sceneId}`}</FormLabel>
                      <FormControl>
                        <Textarea rows={3} {...field} />
                      </FormControl>
                      <CharacterCounter
                        length={field.value.trim().length}
                        max={MAX_SCENE_TEXT_CHARS}
                      />
                      <FormMessage />
                    </FormItem>
                  )}
                />
              ) : (
                <div className="grid gap-4 sm:grid-cols-2">
                  <FormField
                    control={form.control}
                    name={sceneAudioName(index)}
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>{`Audio for scene ${sceneId}`}</FormLabel>
                        <FormControl>
                          <Input
                            type="file"
                            accept="audio/*"
                            name={field.name}
                            ref={field.ref}
                            onBlur={field.onBlur}
                            onChange={(event) => {
                              field.onChange(event.target.files?.[0]);
                            }}
                          />
                        </FormControl>
                        <FormDescription>Up to 25 MB.</FormDescription>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name={sceneTextName(index)}
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>{`Text for scene ${sceneId} (optional)`}</FormLabel>
                        <FormControl>
                          <Textarea rows={2} {...field} />
                        </FormControl>
                        <CharacterCounter
                          length={field.value.trim().length}
                          max={MAX_SCENE_TEXT_CHARS}
                        />
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </div>
              )}
            </li>
          ))}
        </ol>
      )}
      {sceneIds.length > 0 ? (
        <div>
          <CharacterCounter length={totalLength} max={MAX_TOTAL_TEXT_CHARS} />
          {form.formState.errors.scenes?.message ? (
            <p role="alert" className="text-sm text-destructive">
              {form.formState.errors.scenes.message}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
