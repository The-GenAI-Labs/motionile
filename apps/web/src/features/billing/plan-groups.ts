import type { PlanGroup, Product } from "@/features/billing/types/billing.types";
import { titleCase } from "@/lib/utils/format";

export type BillingInterval = "month" | "year";

export const INTERVAL_ORDER: readonly BillingInterval[] = ["month", "year"];

export const intervalNouns: Readonly<Record<BillingInterval, string>> = {
  month: "month",
  year: "year",
};

export const groupPlans = (subscriptions: readonly Product[]): PlanGroup[] => {
  const groups = new Map<string, PlanGroup>();
  for (const product of subscriptions) {
    if (product.interval === null) {
      continue;
    }
    const planKey = product.planKey ?? product.code;
    const group = groups.get(planKey) ?? {
      planKey,
      name: titleCase(planKey),
      byInterval: {},
    };
    group.byInterval[product.interval] = product;
    groups.set(planKey, group);
  }
  return [...groups.values()];
};

export const availableIntervals = (groups: readonly PlanGroup[]): BillingInterval[] =>
  INTERVAL_ORDER.filter((interval) => groups.some((group) => group.byInterval[interval]));

export const planCheckoutPath = (productCode: string): string =>
  `/billing/plans?plan=${encodeURIComponent(productCode)}`;

export const packCheckoutPath = (productCode: string): string =>
  `/billing/credits?pack=${encodeURIComponent(productCode)}`;
