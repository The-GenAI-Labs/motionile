"use client";

import { useQuery } from "@tanstack/react-query";

import { evaluatedFlags, publicSettings } from "@/features/platform/api/platform.api";
import { platformKeys } from "@/features/platform/query-keys";

export const useFlags = () =>
  useQuery({ queryKey: platformKeys.flags(), queryFn: evaluatedFlags, staleTime: 60_000 });

export const useFlag = (key: string): boolean => useFlags().data?.flags[key] ?? false;

export const usePublicSettings = () =>
  useQuery({
    queryKey: platformKeys.publicSettings(),
    queryFn: publicSettings,
    staleTime: 300_000,
  });
