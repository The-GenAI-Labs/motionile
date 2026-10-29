"use client";

import { useId } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { StyleSwatch } from "@/features/generation/components/style-swatch";
import type { StyleOption } from "@/features/generation/types/generation.types";

interface StylePickerProps {
  styles: readonly StyleOption[] | undefined;
  isLoading: boolean;
  isError: boolean;
  value: string;
  onChange: (slug: string) => void;
  error?: string | undefined;
}

export function StylePicker({
  styles,
  isLoading,
  isError,
  value,
  onChange,
  error,
}: StylePickerProps) {
  const name = useId();
  const descriptionId = useId();
  return (
    <fieldset className="space-y-3" aria-describedby={error ? descriptionId : undefined}>
      <legend className="text-sm font-medium">Visual style</legend>
      {isLoading ? <Skeleton className="h-32 w-full" /> : null}
      {isError ? (
        <p role="alert" className="text-sm text-destructive">
          Styles could not be loaded. Reload the page to try again.
        </p>
      ) : null}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {styles?.map((style) => (
          <label key={style.slug} className="cursor-pointer">
            <input
              type="radio"
              name={name}
              value={style.slug}
              checked={style.slug === value}
              className="peer sr-only"
              onChange={() => {
                onChange(style.slug);
              }}
            />
            <span className="flex h-full flex-col gap-2 rounded-lg border bg-surface p-3 transition-colors peer-checked:border-ring peer-checked:bg-elevated peer-focus-visible:ring-[3px] peer-focus-visible:ring-ring hover:bg-elevated">
              <StyleSwatch style={style} />
              <span className="text-sm font-medium">{style.name}</span>
              <span className="text-xs text-subtle-foreground">{style.description}</span>
            </span>
          </label>
        ))}
      </div>
      {error ? (
        <p id={descriptionId} role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </fieldset>
  );
}
