import { z } from "zod";

import type {
  AdminJobScene,
  IssueCount,
  ReportSummary,
} from "@/features/admin-jobs/types/admin-jobs.types";

export const ADMIN_JOBS_PAGE_SIZE = 25;

export const startOfDay = (date: string): string => `${date}T00:00:00.000Z`;

export const endOfDay = (date: string): string => `${date}T23:59:59.999Z`;

export const isUuid = (value: string): boolean => z.uuid().safeParse(value).success;

export const isIsoDate = (value: string): boolean => z.iso.date().safeParse(value).success;

const reportSchema = z.looseObject({
  valid: z.boolean().optional(),
  errors: z.number().optional(),
  warnings: z.number().optional(),
  issues: z.array(z.looseObject({ code: z.string().optional() })).optional(),
  skipped: z.array(z.unknown()).optional(),
});

export const countIssueCodes = (codes: readonly string[]): IssueCount[] => {
  const counts = new Map<string, number>();
  for (const code of codes) {
    counts.set(code, (counts.get(code) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([code, count]) => ({ code, count }))
    .toSorted((a, b) => b.count - a.count || a.code.localeCompare(b.code));
};

export const summarizeReport = (value: unknown): ReportSummary | null => {
  const parsed = reportSchema.safeParse(value);
  if (!parsed.success) {
    return null;
  }
  const report = parsed.data;
  return {
    valid: report.valid ?? null,
    errors: report.errors ?? null,
    warnings: report.warnings ?? null,
    issueCounts: countIssueCodes((report.issues ?? []).map((issue) => issue.code ?? "unknown")),
    skipped: report.skipped?.length ?? 0,
  };
};

const attemptSchema = z.looseObject({
  attempt: z.number().optional(),
  kind: z.string().optional(),
  issueCodes: z.array(z.string()).optional(),
});

export interface AttemptSummary {
  attempt: number;
  kind: string;
  issueCodes: string[];
}

export const summarizeAttempts = (scene: AdminJobScene): AttemptSummary[] =>
  scene.attemptLog.map((entry, index) => {
    const parsed = attemptSchema.safeParse(entry);
    const data = parsed.success ? parsed.data : {};
    return {
      attempt: data.attempt ?? index + 1,
      kind: data.kind ?? "unknown",
      issueCodes: data.issueCodes ?? [],
    };
  });

export const formatRate = (rate: number | null): string =>
  rate === null ? "No data" : `${(rate * 100).toFixed(1)}%`;

const MICROS_PER_DOLLAR = 1_000_000;

export const formatMicrosUsd = (micros: number): string =>
  `$${(micros / MICROS_PER_DOLLAR).toFixed(4)}`;
