"use client";

import { useQuery } from "@tanstack/react-query";

import { getRender } from "@/features/library/api/library.api";
import { libraryKeys } from "@/features/library/query-keys";

interface UseRenderOptions {
  enabled?: boolean;
  refetchIntervalMs?: number;
}

export const useRender = (
  renderId: string,
  { enabled = true, refetchIntervalMs }: UseRenderOptions = {},
) =>
  useQuery({
    queryKey: libraryKeys.render(renderId),
    queryFn: () => getRender(renderId),
    enabled,
    refetchInterval: refetchIntervalMs ?? false,
  });
