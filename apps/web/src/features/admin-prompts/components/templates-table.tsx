"use client";

import Link from "next/link";

import { createDataTableColumnHelper, DataTable } from "@/components/shared/data-table";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { PromptStatusBadge } from "@/features/admin-prompts/components/prompt-status-badge";
import { adminPromptsErrorMessage } from "@/features/admin-prompts/errors";
import { usePromptTemplates } from "@/features/admin-prompts/hooks/use-admin-prompts";
import { adminPromptsPaths } from "@/features/admin-prompts/paths";
import type { PromptTemplate } from "@/features/admin-prompts/types/admin-prompts.types";

const column = createDataTableColumnHelper<PromptTemplate>();

const columns = [
  column.display({
    id: "key",
    header: "Template",
    cell: ({ row }) => (
      <div className="flex flex-col">
        <Link
          href={adminPromptsPaths.template(row.original.key)}
          className="rounded-sm font-mono font-medium hover:underline focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none"
        >
          {row.original.key}
        </Link>
        {row.original.description ? (
          <span className="max-w-96 truncate text-xs text-muted-foreground">
            {row.original.description}
          </span>
        ) : null}
      </div>
    ),
  }),
  column.display({
    id: "active",
    header: "Active version",
    cell: ({ row }) => (
      <span className="font-mono">
        {row.original.activeVersion === null ? "None" : `v${String(row.original.activeVersion)}`}
      </span>
    ),
  }),
  column.display({
    id: "eval",
    header: "Latest eval",
    cell: ({ row }) => <PromptStatusBadge status={row.original.latestEvalStatus} />,
  }),
  column.display({
    id: "versions",
    header: "Versions",
    cell: ({ row }) => <span className="font-mono">{row.original.versionCount}</span>,
  }),
];

export function TemplatesTable() {
  const templates = usePromptTemplates();
  if (templates.isPending) {
    return (
      <Skeleton
        role="status"
        aria-hidden={false}
        aria-label="Loading prompt templates"
        className="h-64"
      />
    );
  }
  if (templates.isError) {
    return (
      <div role="alert" className="flex flex-wrap items-center gap-3 text-sm text-destructive">
        <p>{adminPromptsErrorMessage(templates.error)}</p>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            void templates.refetch();
          }}
        >
          Try again
        </Button>
      </div>
    );
  }
  return (
    <DataTable
      caption="Prompt templates"
      columns={columns}
      data={templates.data.items}
      getRowId={(template) => template.key}
      emptyState="No prompt templates have been seeded yet."
    />
  );
}
