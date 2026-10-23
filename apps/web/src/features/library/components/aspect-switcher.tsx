"use client";

import { useId } from "react";

import { aspectDescriptions, aspectLabels } from "@/features/library/schemas/library.schema";
import type { Aspect } from "@/features/library/types/library.types";

interface AspectSwitcherProps {
  aspects: readonly Aspect[];
  value: Aspect;
  onChange: (aspect: Aspect) => void;
}

export function AspectSwitcher({ aspects, value, onChange }: AspectSwitcherProps) {
  const name = useId();
  return (
    <fieldset role="radiogroup" className="flex flex-wrap items-center gap-2">
      <legend className="sr-only">Aspect ratio</legend>
      {aspects.map((aspect) => (
        <label key={aspect} className="cursor-pointer">
          <input
            type="radio"
            name={name}
            value={aspect}
            checked={aspect === value}
            aria-label={`${aspectLabels[aspect]} ${aspectDescriptions[aspect].toLowerCase()}`}
            className="peer sr-only"
            onChange={() => {
              onChange(aspect);
            }}
          />
          <span
            aria-hidden="true"
            className="inline-flex h-8 items-center rounded-md border bg-surface px-3 font-mono text-xs text-subtle-foreground transition-colors peer-checked:border-ring peer-checked:bg-elevated peer-checked:text-foreground peer-focus-visible:ring-[3px] peer-focus-visible:ring-ring hover:bg-elevated"
          >
            {aspectLabels[aspect]}
          </span>
        </label>
      ))}
    </fieldset>
  );
}
