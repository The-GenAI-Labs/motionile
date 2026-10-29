"use client";

import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import {
  DURATION_MAX_SECONDS,
  DURATION_MIN_SECONDS,
  DURATION_STEP_SECONDS,
} from "@/features/generation/schemas/generation.schema";

interface DurationFieldProps {
  value: number;
  onChange: (seconds: number) => void;
}

export function DurationField({ value, onChange }: DurationFieldProps) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <Label id="duration-label">Length</Label>
        <output aria-live="polite" className="font-mono text-sm">
          {`${String(value)} seconds`}
        </output>
      </div>
      <Slider
        min={DURATION_MIN_SECONDS}
        max={DURATION_MAX_SECONDS}
        step={DURATION_STEP_SECONDS}
        value={[value]}
        thumbLabel="Video length in seconds"
        thumbValueText={`${String(value)} seconds`}
        onValueChange={([next = value]) => {
          onChange(next);
        }}
      />
      <div
        className="flex justify-between font-mono text-xs text-muted-foreground"
        aria-hidden="true"
      >
        <span>{DURATION_MIN_SECONDS} s</span>
        <span>{DURATION_MAX_SECONDS} s</span>
      </div>
    </div>
  );
}
