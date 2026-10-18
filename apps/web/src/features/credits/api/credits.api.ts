import * as contract from "@motionile/api-contract";

import { apiClient } from "@/lib/api/client";

export const CREDITS_PAGE_SIZE = 20;

export const getWallet = async () =>
  contract.zCreditsWalletResponse.parse(
    (await apiClient.get<unknown>("/v1/credits/wallet", { authenticated: true })).data,
  );

export const listLedger = async (cursor?: string) =>
  contract.zCreditsLedgerResponse.parse(
    (
      await apiClient.get<unknown>("/v1/credits/ledger", {
        authenticated: true,
        params: contract.zCreditsLedgerQuery.parse({ cursor, limit: CREDITS_PAGE_SIZE }),
      })
    ).data,
  );

export const listUsage = async (cursor?: string) =>
  contract.zUsagePageResponse.parse(
    (
      await apiClient.get<unknown>("/v1/credits/usage", {
        authenticated: true,
        params: contract.zCreditsUsageQuery.parse({ cursor, limit: CREDITS_PAGE_SIZE }),
      })
    ).data,
  );

export const listDailyUsage = async () =>
  contract.zDailyUsageListResponse.parse(
    (
      await apiClient.get<unknown>("/v1/credits/usage", {
        authenticated: true,
        params: contract.zCreditsUsageQuery.parse({ aggregate: "daily" }),
      })
    ).data,
  );
