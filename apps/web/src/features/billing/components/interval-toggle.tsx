import { useId } from "react";

import { type BillingInterval, INTERVAL_ORDER } from "@/features/billing/plan-groups";
import { cn } from "@/lib/utils/cn";

const labels: Readonly<Record<BillingInterval, string>> = {
  month: "Monthly",
  year: "Yearly",
};

interface IntervalToggleProps {
  value: BillingInterval;
  onChange: (value: BillingInterval) => void;
  intervals?: readonly BillingInterval[];
}

export function IntervalToggle({
  value,
  onChange,
  intervals = INTERVAL_ORDER,
}: IntervalToggleProps) {
  const name = useId();
  return (
    <fieldset>
      <legend className="sr-only">Billing period</legend>
      <div className="inline-flex rounded-lg border bg-surface p-1">
        {intervals.map((interval) => (
          <label key={interval} className="relative cursor-pointer">
            <input
              type="radio"
              name={name}
              value={interval}
              checked={value === interval}
              onChange={() => {
                onChange(interval);
              }}
              className="peer sr-only"
            />
            <span
              className={cn(
                "block w-24 rounded-md px-3 py-1.5 text-center text-sm font-medium text-muted-foreground transition-colors",
                "peer-checked:bg-elevated peer-checked:text-foreground peer-focus-visible:ring-[3px] peer-focus-visible:ring-ring",
              )}
            >
              {labels[interval]}
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
