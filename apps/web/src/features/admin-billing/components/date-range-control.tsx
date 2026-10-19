"use client";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  defaultDateRange,
  isValidDateRange,
  MAX_RANGE_DAYS,
} from "@/features/admin-billing/schemas/admin-billing.schema";
import type { DateRange } from "@/features/admin-billing/types/admin-billing.types";

const PRESET_DAYS = [7, 30, 90] as const;

interface DateRangeControlProps {
  from: string;
  to: string;
  onChange: (range: DateRange) => void;
}

export function DateRangeControl({ from, to, onChange }: DateRangeControlProps) {
  const valid = isValidDateRange(from, to);
  return (
    <section aria-label="Date range" className="space-y-3 rounded-xl border bg-surface p-4">
      <div className="grid gap-3 sm:grid-cols-[repeat(2,minmax(0,12rem))_1fr] sm:items-end">
        <div className="space-y-1">
          <Label htmlFor="range-from">From</Label>
          <Input
            id="range-from"
            type="date"
            value={from}
            max={to}
            aria-invalid={!valid}
            onChange={(event) => {
              onChange({ from: event.target.value, to });
            }}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="range-to">To</Label>
          <Input
            id="range-to"
            type="date"
            value={to}
            min={from}
            aria-invalid={!valid}
            onChange={(event) => {
              onChange({ from, to: event.target.value });
            }}
          />
        </div>
        <div className="flex flex-wrap gap-2">
          {PRESET_DAYS.map((days) => (
            <Button
              key={days}
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                onChange(defaultDateRange(new Date(), days));
              }}
            >
              Last {days} days
            </Button>
          ))}
        </div>
      </div>
      {valid ? null : (
        <p role="alert" className="text-sm text-destructive">
          Choose a range of 1 to {MAX_RANGE_DAYS} days that ends on or after the day it starts.
        </p>
      )}
    </section>
  );
}
