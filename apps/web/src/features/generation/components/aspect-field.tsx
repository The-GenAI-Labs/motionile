"use client";

import { aspectChoices } from "@/features/generation/schemas/generation.schema";
import type { Aspect } from "@/features/generation/types/generation.types";

interface AspectFieldProps {
  value: readonly Aspect[];
  allowed: readonly Aspect[];
  onChange: (aspects: Aspect[]) => void;
  error?: string | undefined;
}

export function AspectField({ value, allowed, onChange, error }: AspectFieldProps) {
  const toggle = (aspect: Aspect) => {
    if (value.includes(aspect)) {
      if (value.length > 1) {
        onChange(value.filter((item) => item !== aspect));
      }
      return;
    }
    onChange(
      aspectChoices
        .map((choice) => choice.value)
        .filter((item) => item === aspect || value.includes(item)),
    );
  };
  return (
    <div role="group" aria-labelledby="aspect-legend" className="space-y-2">
      <p id="aspect-legend" className="text-sm font-medium">
        Aspect ratios
      </p>
      <div className="flex flex-wrap gap-2">
        {aspectChoices
          .filter((choice) => allowed.includes(choice.value))
          .map((choice) => {
            const pressed = value.includes(choice.value);
            return (
              <button
                key={choice.value}
                type="button"
                aria-pressed={pressed}
                aria-label={`${choice.label} ${choice.description.toLowerCase()}`}
                onClick={() => {
                  toggle(choice.value);
                }}
                className="inline-flex h-10 items-center gap-2 rounded-md border bg-surface px-4 font-mono text-sm transition-colors outline-none hover:bg-elevated focus-visible:ring-[3px] focus-visible:ring-ring aria-pressed:border-ring aria-pressed:bg-elevated"
              >
                <span aria-hidden="true">{pressed ? "On" : "Off"}</span>
                {choice.label}
              </button>
            );
          })}
      </div>
      <p className="text-xs text-muted-foreground">
        Each extra ratio adds to the cost. Choose at least one.
      </p>
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}
