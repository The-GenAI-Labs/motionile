"use client";

import { useQuery } from "@tanstack/react-query";

import { getWallet } from "@/features/credits/api/credits.api";
import { creditsKeys } from "@/features/credits/query-keys";

export const WALLET_STALE_TIME_MS = 30_000;

export const useWallet = () =>
  useQuery({
    queryKey: creditsKeys.wallet(),
    queryFn: getWallet,
    staleTime: WALLET_STALE_TIME_MS,
  });
