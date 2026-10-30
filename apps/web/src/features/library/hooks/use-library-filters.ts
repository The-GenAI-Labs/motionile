"use client";

import { parseAsString, parseAsStringLiteral, useQueryStates } from "nuqs";

import {
  ASPECT_ORDER,
  SEARCH_DEBOUNCE_MS,
  toLibraryFilters,
} from "@/features/library/schemas/library.schema";
import type { LibraryFilters } from "@/features/library/types/library.types";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";

export const libraryFilterParsers = {
  q: parseAsString.withDefault(""),
  aspect: parseAsStringLiteral(ASPECT_ORDER),
};

export const useLibraryFilters = () => {
  const [state, setState] = useQueryStates(libraryFilterParsers, { history: "replace" });
  const search = useDebouncedValue(state.q, SEARCH_DEBOUNCE_MS);
  const filters: LibraryFilters = toLibraryFilters(search, state.aspect);
  const active = state.q.trim() !== "" || state.aspect !== null;
  return { state, setState, filters, active };
};
