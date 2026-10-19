import type { zLedgerReasonName, zLotSourceName } from "@motionile/api-contract";
import { z } from "zod";

export const usageViewSchema = z.enum(["entries", "daily"]);

export const ledgerReasonLabels = {
  purchase: "Credit pack purchase",
  subscription_grant: "Subscription credits",
  promo_grant: "Promotional credits",
  admin_adjust: "Adjustment by support",
  reserve: "Reserved for a task",
  commit: "Spent on a task",
  release: "Reservation released",
  refund_clawback: "Refund adjustment",
  expiry: "Credits expired",
} as const satisfies Record<z.infer<typeof zLedgerReasonName>, string>;

export const lotSourceLabels = {
  purchase: "Credit pack",
  subscription: "Subscription",
  admin: "Support",
  promo: "Promotion",
} as const satisfies Record<z.infer<typeof zLotSourceName>, string>;
