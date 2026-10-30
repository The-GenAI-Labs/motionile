"use client";

import { zSkillLayer } from "@motionile/api-contract";
import Link from "next/link";

import { createDataTableColumnHelper } from "@/components/shared/data-table";
import { FilterPanel, optionsFromValues, SelectFilter } from "@/components/shared/filter-fields";
import { PagedTable } from "@/components/shared/paged-table";
import { Badge } from "@/components/ui/badge";
import { EmbeddingBadge } from "@/features/admin-skills/components/embedding-badge";
import { adminSkillsErrorMessage } from "@/features/admin-skills/errors";
import { useSystemSkills } from "@/features/admin-skills/hooks/use-admin-skills";
import {
  toSkillFilters,
  useSkillFilterState,
} from "@/features/admin-skills/hooks/use-skill-filters";
import { adminSkillsPaths } from "@/features/admin-skills/paths";
import { checksumPrefix } from "@/features/admin-skills/schemas/admin-skills.schema";
import type { SystemSkill } from "@/features/admin-skills/types/admin-skills.types";
import { flattenCursorPages } from "@/lib/api/pagination";
import { formatCredits, formatDate } from "@/lib/utils/format";

const column = createDataTableColumnHelper<SystemSkill>();

const columns = [
  column.display({
    id: "name",
    header: "Skill",
    cell: ({ row }) => (
      <div className="flex max-w-80 flex-col">
        <Link
          href={adminSkillsPaths.skill(row.original.slug)}
          className="truncate rounded-sm font-medium hover:underline focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none"
        >
          {row.original.name}
        </Link>
        <span className="font-mono text-xs text-muted-foreground">{row.original.slug}</span>
      </div>
    ),
  }),
  column.display({
    id: "layer",
    header: "Layer",
    cell: ({ row }) => <Badge variant="outline">{row.original.layer}</Badge>,
  }),
  column.display({
    id: "version",
    header: "Version",
    cell: ({ row }) => <span className="font-mono">v{row.original.version}</span>,
  }),
  column.display({
    id: "checksum",
    header: "Checksum",
    cell: ({ row }) => (
      <span className="font-mono text-xs">{checksumPrefix(row.original.checksum)}</span>
    ),
  }),
  column.display({
    id: "tokens",
    header: "Tokens",
    cell: ({ row }) => <span className="font-mono">{formatCredits(row.original.tokenCount)}</span>,
  }),
  column.display({
    id: "embedding",
    header: "Embedding",
    cell: ({ row }) => <EmbeddingBadge status={row.original.embeddingStatus} />,
  }),
  column.display({
    id: "updated",
    header: "Updated",
    cell: ({ row }) => formatDate(row.original.updatedAt),
  }),
];

export function SkillsTable() {
  const [state, setState] = useSkillFilterState();
  const skills = useSystemSkills(toSkillFilters(state));
  return (
    <div className="space-y-5">
      <FilterPanel
        label="Skill filters"
        onClear={() => {
          void setState(null);
        }}
      >
        <SelectFilter
          id="skill-layer"
          label="Layer"
          value={state.layer ?? ""}
          options={optionsFromValues(zSkillLayer.options)}
          onChange={(value) => {
            const layer = zSkillLayer.safeParse(value);
            void setState({ layer: layer.success ? layer.data : null });
          }}
        />
      </FilterPanel>
      <PagedTable
        caption="System skills"
        columns={columns}
        rows={flattenCursorPages(skills.data?.pages)}
        getRowId={(skill) => skill.slug}
        isPending={skills.isPending}
        errorMessage={skills.isError ? adminSkillsErrorMessage(skills.error) : null}
        onRetry={() => {
          void skills.refetch();
        }}
        emptyState="No system skills match these filters."
        hasNextPage={skills.hasNextPage}
        isFetchingNextPage={skills.isFetchingNextPage}
        fetchNextPage={skills.fetchNextPage}
      />
    </div>
  );
}
