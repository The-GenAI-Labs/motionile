"use client";

import { createDataTableColumnHelper } from "@/components/shared/data-table";
import { PagedTable } from "@/components/shared/paged-table";
import { Badge } from "@/components/ui/badge";
import { DetailSection } from "@/features/admin-billing/components/detail-section";
import { PromptStatusBadge } from "@/features/admin-prompts/components/prompt-status-badge";
import { ActivateVersionButton } from "@/features/admin-prompts/components/version-controls";
import { adminPromptsErrorMessage } from "@/features/admin-prompts/errors";
import type { usePromptVersions } from "@/features/admin-prompts/hooks/use-admin-prompts";
import type { PromptVersion } from "@/features/admin-prompts/types/admin-prompts.types";
import { flattenCursorPages } from "@/lib/api/pagination";
import { formatDateTime } from "@/lib/utils/format";

const column = createDataTableColumnHelper<PromptVersion>();

const columnsFor = (templateKey: string) => [
  column.display({
    id: "version",
    header: "Version",
    cell: ({ row }) => (
      <div className="flex items-center gap-2">
        <span className="font-mono">v{row.original.version}</span>
        {row.original.isActive ? <Badge variant="success">Active</Badge> : null}
      </div>
    ),
  }),
  column.display({
    id: "eval",
    header: "Eval status",
    cell: ({ row }) => <PromptStatusBadge status={row.original.evalStatus} />,
  }),
  column.display({
    id: "checksum",
    header: "Checksum",
    cell: ({ row }) => <span className="font-mono text-xs">{row.original.checksumPrefix}</span>,
  }),
  column.display({
    id: "created",
    header: "Created",
    cell: ({ row }) => formatDateTime(row.original.createdAt),
  }),
  column.display({
    id: "actions",
    header: () => <span className="sr-only">Actions</span>,
    cell: ({ row }) => <ActivateVersionButton templateKey={templateKey} version={row.original} />,
  }),
];

interface VersionsPanelProps {
  templateKey: string;
  versions: ReturnType<typeof usePromptVersions>;
}

export function VersionsPanel({ templateKey, versions }: VersionsPanelProps) {
  return (
    <DetailSection title="Versions">
      <PagedTable
        caption={`Versions of ${templateKey}`}
        columns={columnsFor(templateKey)}
        rows={flattenCursorPages(versions.data?.pages)}
        getRowId={(version) => version.id}
        isPending={versions.isPending}
        errorMessage={versions.isError ? adminPromptsErrorMessage(versions.error) : null}
        onRetry={() => {
          void versions.refetch();
        }}
        emptyState="This template has no versions yet."
        hasNextPage={versions.hasNextPage}
        isFetchingNextPage={versions.isFetchingNextPage}
        fetchNextPage={versions.fetchNextPage}
      />
    </DetailSection>
  );
}
