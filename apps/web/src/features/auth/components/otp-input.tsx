"use client";
import { useId, useRef } from "react";

import { Input } from "@/components/ui/input";
export function OtpInput({
  value,
  onChange,
  onComplete,
  disabled = false,
}: {
  value: string;
  onChange: (value: string) => void;
  onComplete?: (value: string) => void;
  disabled?: boolean;
}) {
  const labelId = useId();
  const inputs = useRef<(HTMLInputElement | null)[]>([]);
  const update = (next: string, focus: number) => {
    onChange(next);
    inputs.current[Math.min(5, Math.max(0, focus))]?.focus();
    if (next !== value && /^\d{6}$/.test(next)) onComplete?.(next);
  };
  return (
    <div role="group" aria-labelledby={labelId}>
      <p id={labelId} className="mb-2 text-sm font-medium">
        Verification code
      </p>
      <div className="flex gap-2">
        {Array.from({ length: 6 }, (_, index) => (
          <Input
            key={index}
            ref={(element) => {
              inputs.current[index] = element;
            }}
            aria-label={`Digit ${String(index + 1)}`}
            autoComplete={index === 0 ? "one-time-code" : "off"}
            inputMode="numeric"
            pattern="[0-9]*"
            maxLength={6}
            disabled={disabled}
            value={(value[index] ?? "").trim()}
            className="h-12 min-w-0 text-center font-mono text-lg"
            onPaste={(event) => {
              event.preventDefault();
              const pasted = event.clipboardData.getData("text").replace(/\D/g, "").slice(0, 6);
              update(pasted, pasted.length);
            }}
            onChange={(event) => {
              const digits = event.target.value.replace(/\D/g, "");
              if (digits.length > 1) update(digits.slice(0, 6), digits.length);
              else {
                const padded = value.padEnd(6, " ");
                const next = (
                  padded.slice(0, index) +
                  (digits || " ") +
                  padded.slice(index + 1)
                ).trimEnd();
                update(next, digits ? index + 1 : index);
              }
            }}
            onKeyDown={(event) => {
              if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
                event.preventDefault();
                inputs.current[
                  Math.max(0, Math.min(5, index + (event.key === "ArrowLeft" ? -1 : 1)))
                ]?.focus();
              }
              if (event.key === "Backspace" && !(value[index] ?? "").trim() && index > 0) {
                event.preventDefault();
                const padded = value.padEnd(6, " ");
                update(
                  (padded.slice(0, index - 1) + " " + padded.slice(index)).trimEnd(),
                  index - 1,
                );
              }
            }}
          />
        ))}
      </div>
    </div>
  );
}
