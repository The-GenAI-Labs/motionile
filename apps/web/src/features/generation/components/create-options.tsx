"use client";

import { Controller, type UseFormReturn, useWatch } from "react-hook-form";

import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import { Switch } from "@/components/ui/switch";
import type { CreateJobFormValues } from "@/features/generation/schemas/generation.schema";

const languageName = (code: string): string => {
  try {
    return new Intl.DisplayNames(["en"], { type: "language" }).of(code) ?? code;
  } catch {
    return code;
  }
};

interface SwitchRowProps {
  id: string;
  label: string;
  description: string;
  checked: boolean;
  disabled?: boolean;
  error?: string | undefined;
  onChange: (checked: boolean) => void;
}

function SwitchRow({
  id,
  label,
  description,
  checked,
  disabled = false,
  error,
  onChange,
}: SwitchRowProps) {
  return (
    <div className="flex items-start gap-3">
      <Switch id={id} checked={checked} disabled={disabled} onCheckedChange={onChange} />
      <div className="space-y-1">
        <Label htmlFor={id}>{label}</Label>
        <p className="text-xs text-muted-foreground">{description}</p>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </div>
    </div>
  );
}

interface CreateOptionsProps {
  form: UseFormReturn<CreateJobFormValues>;
  languages: readonly string[];
}

export function CreateOptions({ form, languages }: CreateOptionsProps) {
  const { control, formState, setValue } = form;
  const subtitles = useWatch({ control, name: "subtitles" });
  return (
    <div className="space-y-5">
      <Controller
        control={control}
        name="language"
        render={({ field }) => (
          <div className="space-y-2">
            <Label htmlFor="create-language">Language</Label>
            <NativeSelect id="create-language" value={field.value} onChange={field.onChange}>
              {languages.map((code) => (
                <option key={code} value={code}>
                  {languageName(code)}
                </option>
              ))}
            </NativeSelect>
          </div>
        )}
      />
      <Controller
        control={control}
        name="reviewStoryboard"
        render={({ field }) => (
          <SwitchRow
            id="create-review"
            label="Review storyboard before rendering"
            description="Pause after planning so you can edit the scenes and approve them."
            checked={field.value}
            onChange={field.onChange}
          />
        )}
      />
      <Controller
        control={control}
        name="subtitles"
        render={({ field }) => (
          <SwitchRow
            id="create-subtitles"
            label="Subtitles"
            description="Create subtitle files (VTT and SRT) for the video."
            checked={field.value}
            onChange={(checked) => {
              field.onChange(checked);
              if (!checked) {
                setValue("burnInSubtitles", false, { shouldValidate: true });
              }
            }}
          />
        )}
      />
      <Controller
        control={control}
        name="burnInSubtitles"
        render={({ field }) => (
          <SwitchRow
            id="create-burn-in"
            label="Burn subtitles into the video"
            description="Draw the subtitles on the picture. Needs subtitles to be on."
            checked={field.value}
            disabled={!subtitles}
            error={formState.errors.burnInSubtitles?.message}
            onChange={field.onChange}
          />
        )}
      />
    </div>
  );
}
