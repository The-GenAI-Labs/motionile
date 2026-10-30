"use client";

import { zRunStatus } from "@motionile/api-contract";
import { useState } from "react";

import { createDataTableColumnHelper } from "@/components/shared/data-table";
import { optionsFromValues, SelectFilter } from "@/components/shared/filter-fields";
import { PagedTable } from "@/components/shared/paged-table";
import { PermissionGate } from "@/components/shared/permission-gate";
import { DetailSection } from "@/features/admin-billing/components/detail-section";
import { PromptStatusBadge } from "@/features/admin-prompts/components/prompt-status-badge";
import { StartEvalDialog } from "@/features/admin-prompts/components/start-eval-dialog";
import { adminPromptsErrorMessage } from "@/features/admin-prompts/errors";
import { useEvalRuns } from "@/features/admin-prompts/hooks/use-admin-prompts";
import { EVAL_SUITES } from "@/features/admin-prompts/schemas/admin-prompts.schema";
import type {
  EvalRun,
  EvalRunFilters,
  PromptVersion,
} from "@/features/admin-prompts/types/admin-prompts.types";
import { flattenCursorPages } from "@/lib/api/pagination";
import { formatDateTime } from "@/lib/utils/format";

const column = createDataTableColumnHelper<EvalRun>();

const versionLabels = (run: EvalRun, versions: readonly PromptVersion[]): string =>
  run.promptVersionIds
    .map((id) => {
      const found = versions.find((version) => version.id === id);
      return found === undefined ? "unknown" : `v${String(found.version)}`;
    })
    .join(", ");

const columnsFor = (versions: readonly PromptVersion[]) => [
  column.display({
    id: "suite",
    header: "Suite",
    cell: ({ row }) => <span className="font-mono">{row.original.suite}</span>,
  }),
  column.display({
    id: "status",
    header: "Status",
    cell: ({ row }) => (
      <div className="flex flex-col gap-1">
        <PromptStatusBadge status={row.original.status} />
        {row.original.passed === null ? null : (
          <PromptStatusBadge status={row.original.passed ? "passed" : "failed"} />
        )}
        {row.original.errorCode ? (
          <span className="font-mono text-xs text-destructive">{row.original.errorCode}</span>
        ) : null}
      </div>
    ),
  }),
  column.display({
    id: "versions",
    header: "Versions",
    cell: ({ row }) => <span className="font-mono">{versionLabels(row.original, versions)}</span>,
  }),
  column.display({
    id: "trigger",
    header: "Trigger",
    cell: ({ row }) => <span className="font-mono">{row.original.trigger}</span>,
  }),
  column.display({
    id: "started",
    header: "Started",
    cell: ({ row }) => formatDateTime(row.original.startedAt),
  }),
  column.display({
    id: "finished",
    header: "Finished",
    cell: ({ row }) =>
      row.original.finishedAt ? formatDateTime(row.original.finishedAt) : "Not finished",
  }),
];

export function EvalRunsPanel({ versions }: { versions: readonly PromptVersion[] }) {
  const [suite, setSuite] = useState("");
  const [status, setStatus] = useState("");
  const parsedStatus = zRunStatus.safeParse(status);
  const filters: EvalRunFilters = {
    ...(suite === "" ? {} : { suite }),
    ...(parsedStatus.success ? { status: parsedStatus.data } : {}),
  };
  const runs = useEvalRuns(filters);
  const versionIds = new Set(versions.map((version) => version.id));
  const rows = flattenCursorPages(runs.data?.pages).filter((run) =>
    run.promptVersionIds.some((id) => versionIds.has(id)),
  );
  return (
    <DetailSection
      title="Evaluation runs"
      actions={
        <PermissionGate required={["evals.run"]}>
          <StartEvalDialog versions={versions} />
        </PermissionGate>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <SelectFilter
          id="eval-suite"
          label="Suite"
          value={suite}
          options={optionsFromValues(EVAL_SUITES)}
          onChange={setSuite}
        />
        <SelectFilter
          id="eval-status"
          label="Run status"
          value={status}
          options={optionsFromValues(zRunStatus.options)}
          onChange={setStatus}
        />
      </div>
      <PagedTable
        caption="Evaluation runs"
        columns={columnsFor(versions)}
        rows={rows}
        getRowId={(run) => run.id}
        isPending={runs.isPending}
        errorMessage={runs.isError ? adminPromptsErrorMessage(runs.error) : null}
        onRetry={() => {
          void runs.refetch();
        }}
        emptyState="No evaluation runs cover these versions yet."
        hasNextPage={runs.hasNextPage}
        isFetchingNextPage={runs.isFetchingNextPage}
        fetchNextPage={runs.fetchNextPage}
      />
    </DetailSection>
  );
}
