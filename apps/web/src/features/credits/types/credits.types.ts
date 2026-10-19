import type {
  zDailyUsageResponse,
  zExpiringLotResponse,
  zLedgerEntryResponse,
  zLedgerReasonName,
  zLotSourceName,
  zUsageEntryResponse,
  zWalletResponse,
} from "@motionile/api-contract";
import type { z } from "zod";

export type Wallet = z.output<typeof zWalletResponse>;
export type ExpiringLot = z.output<typeof zExpiringLotResponse>;
export type LedgerEntry = z.output<typeof zLedgerEntryResponse>;
export type LedgerReason = z.output<typeof zLedgerReasonName>;
export type LotSource = z.output<typeof zLotSourceName>;
export type UsageEntry = z.output<typeof zUsageEntryResponse>;
export type DailyUsage = z.output<typeof zDailyUsageResponse>;
