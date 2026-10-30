"use client";

import { zJobSource, zJobStatus } from "@motionile/api-contract";
import { parseAsString, parseAsStringLiteral, useQueryStates } from "nuqs";

import {
  endOfDay,
  isIsoDate,
  isUuid,
  startOfDay,
} from "@/features/admin-jobs/schemas/admin-jobs.schema";
import type { AdminJobFilters } from "@/features/admin-jobs/types/admin-jobs.types";

const text = parseAsString.withDefault("");

export const jobFilterParsers = {
  status: parseAsStringLiteral(zJobStatus.options),
  source: parseAsStringLiteral(zJobSource.options),
  user: text,
  from: text,
  to: text,
};

export const useJobFilterState = () => useQueryStates(jobFilterParsers, { history: "replace" });

type JobFilterState = ReturnType<typeof useJobFilterState>[0];

export const toJobFilters = (state: JobFilterState): AdminJobFilters => ({
  ...(state.status === null ? {} : { status: state.status }),
  ...(state.source === null ? {} : { source: state.source }),
  ...(isUuid(state.user) ? { userId: state.user } : {}),
  ...(isIsoDate(state.from) ? { createdFrom: startOfDay(state.from) } : {}),
  ...(isIsoDate(state.to) ? { createdTo: endOfDay(state.to) } : {}),
});
