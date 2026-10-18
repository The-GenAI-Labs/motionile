"use client";

import { useQuery } from "@tanstack/react-query";

import { listProducts } from "@/features/billing/api/billing.api";
import { billingKeys } from "@/features/billing/query-keys";

export const useProducts = () =>
  useQuery({ queryKey: billingKeys.products(), queryFn: listProducts });
