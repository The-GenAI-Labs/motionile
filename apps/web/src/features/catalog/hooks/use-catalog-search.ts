"use client";

import { useQuery } from "@tanstack/react-query";

import { searchCatalog } from "@/features/catalog/api/catalog.api";
import { catalogKeys } from "@/features/catalog/query-keys";

export const useCatalogSearch = (query: string) =>
  useQuery({
    queryKey: catalogKeys.search(query),
    queryFn: () => searchCatalog(query),
    enabled: query.trim().length >= 2,
    staleTime: 60_000,
  });
