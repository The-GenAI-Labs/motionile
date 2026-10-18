"use client";

import { parseAsString, useQueryStates } from "nuqs";

import { AttentionPanel } from "@/features/admin-billing/components/attention-panel";
import { CreditsPanel } from "@/features/admin-billing/components/credits-panel";
import { DateRangeControl } from "@/features/admin-billing/components/date-range-control";
import { RevenuePanel } from "@/features/admin-billing/components/revenue-panel";
import { SubscriptionsPanel } from "@/features/admin-billing/components/subscriptions-panel";
import {
  defaultDateRange,
  isValidDateRange,
} from "@/features/admin-billing/schemas/admin-billing.schema";

const rangeParsers = {
  from: parseAsString.withDefault(""),
  to: parseAsString.withDefault(""),
};

export function BillingOverview() {
  const [params, setParams] = useQueryStates(rangeParsers, { history: "replace" });
  const fallback = defaultDateRange();
  const from = params.from === "" ? fallback.from : params.from;
  const to = params.to === "" ? fallback.to : params.to;
  const range = isValidDateRange(from, to) ? { from, to } : fallback;
  return (
    <div className="space-y-6">
      <AttentionPanel />
      <DateRangeControl
        from={from}
        to={to}
        onChange={(next) => {
          void setParams(next);
        }}
      />
      <RevenuePanel range={range} />
      <SubscriptionsPanel />
      <CreditsPanel range={range} />
    </div>
  );
}
