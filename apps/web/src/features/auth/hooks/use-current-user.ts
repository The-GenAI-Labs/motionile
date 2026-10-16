"use client";
import { useQuery } from "@tanstack/react-query";

import { currentUser } from "@/features/auth/api/auth.api";
import { authKeys } from "@/features/auth/query-keys";
export const useCurrentUser = () =>
  useQuery({ queryKey: authKeys.me(), queryFn: currentUser, staleTime: 300_000, retry: false });
