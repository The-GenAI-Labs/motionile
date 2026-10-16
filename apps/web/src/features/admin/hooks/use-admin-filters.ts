"use client";

import { parseAsString, useQueryStates } from "nuqs";

export const adminFilterParsers = {
  q: parseAsString.withDefault(""),
  status: parseAsString.withDefault(""),
  role: parseAsString.withDefault(""),
  from: parseAsString.withDefault(""),
  to: parseAsString.withDefault(""),
  sort: parseAsString.withDefault("-created_at"),
};

export const useAdminFilters = () => useQueryStates(adminFilterParsers, { history: "push" });
