"use client";

import { createDataTableColumnHelper } from "@/components/shared/data-table";
import { FilterPanel, optionsFromValues, SelectFilter } from "@/components/shared/filter-fields";
import { PagedTable } from "@/components/shared/paged-table";
import { Badge } from "@/components/ui/badge";
import { EditVoiceDialog } from "@/features/admin-voices/components/edit-voice-dialog";
import { RegeneratePreviewButton } from "@/features/admin-voices/components/regenerate-preview-button";
import { adminVoiceErrorMessage } from "@/features/admin-voices/errors";
import {
  toAdminVoiceFilters,
  useAdminVoiceFilterState,
  voiceStatusValues,
} from "@/features/admin-voices/hooks/use-admin-voice-filters";
import { useAdminVoices } from "@/features/admin-voices/hooks/use-admin-voices";
import { isExposed } from "@/features/admin-voices/schemas/admin-voices.schema";
import type { AdminVoice } from "@/features/admin-voices/types/admin-voices.types";
import { PreviewButton } from "@/features/voices/components/voice-card";
import {
  type PreviewState,
  type PreviewTarget,
  useVoicePreviewPlayer,
} from "@/features/voices/hooks/use-voice-preview-player";
import { languageLabel, voiceLanguageOptions } from "@/features/voices/schemas/voices.schema";
import { flattenCursorPages } from "@/lib/api/pagination";

const column = createDataTableColumnHelper<AdminVoice>();

const statusVariants = {
  pending: "outline",
  ready: "success",
  failed: "destructive",
  disabled: "outline",
} as const satisfies Record<AdminVoice["status"], "outline" | "success" | "destructive">;

const buildColumns = (preview: PreviewState, onTogglePreview: (target: PreviewTarget) => void) => [
  column.display({
    id: "name",
    header: "Name",
    cell: ({ row }) => <span className="font-medium">{row.original.name}</span>,
  }),
  column.display({
    id: "provider",
    header: "Provider",
    cell: ({ row }) => <span className="font-mono">{row.original.provider}</span>,
  }),
  column.display({
    id: "language",
    header: "Language",
    cell: ({ row }) => languageLabel(row.original.language),
  }),
  column.display({
    id: "tags",
    header: "Tags",
    cell: ({ row }) =>
      row.original.tags.length === 0 ? (
        <span className="text-muted-foreground">None</span>
      ) : (
        <span className="text-sm">{row.original.tags.join(", ")}</span>
      ),
  }),
  column.display({
    id: "status",
    header: "Status",
    cell: ({ row }) => (
      <Badge variant={statusVariants[row.original.status]}>
        {row.original.status === "ready"
          ? "Ready"
          : row.original.status === "disabled"
            ? "Disabled"
            : row.original.status === "pending"
              ? "Pending"
              : "Failed"}
      </Badge>
    ),
  }),
  column.display({
    id: "exposed",
    header: "Visibility",
    cell: ({ row }) => (
      <Badge variant={isExposed(row.original) ? "success" : "outline"}>
        {isExposed(row.original) ? "Exposed" : "Hidden"}
      </Badge>
    ),
  }),
  column.display({
    id: "preview",
    header: "Preview",
    cell: ({ row }) =>
      row.original.hasPreview && row.original.status === "ready" ? (
        <PreviewButton voice={row.original} preview={preview} onTogglePreview={onTogglePreview} />
      ) : (
        <span className="text-sm text-muted-foreground">
          {row.original.hasPreview ? "Expose to play" : "No preview"}
        </span>
      ),
  }),
  column.display({
    id: "actions",
    header: () => <span className="sr-only">Actions</span>,
    cell: ({ row }) => (
      <div className="flex flex-wrap items-start gap-2">
        <EditVoiceDialog voice={row.original} />
        <RegeneratePreviewButton voice={row.original} />
      </div>
    ),
  }),
];

export function VoicesTable() {
  const [state, setState] = useAdminVoiceFilterState();
  const voices = useAdminVoices(toAdminVoiceFilters(state));
  const player = useVoicePreviewPlayer();
  return (
    <div className="space-y-5">
      <audio {...player.audioProps} className="hidden" />
      <FilterPanel
        label="Voice filters"
        onClear={() => {
          void setState(null);
        }}
      >
        <SelectFilter
          id="voice-status"
          label="Status"
          value={state.status ?? ""}
          options={optionsFromValues(voiceStatusValues)}
          onChange={(value) => {
            void setState({
              status: voiceStatusValues.find((status) => status === value) ?? null,
            });
          }}
        />
        <SelectFilter
          id="voice-language-filter"
          label="Language"
          value={state.language}
          options={voiceLanguageOptions}
          onChange={(value) => {
            void setState({ language: value || null });
          }}
        />
      </FilterPanel>
      <PagedTable
        caption="Built-in voices"
        columns={buildColumns(player.state, (target) => {
          void player.toggle(target);
        })}
        rows={flattenCursorPages(voices.data?.pages)}
        getRowId={(voice) => voice.id}
        isPending={voices.isPending}
        errorMessage={voices.isError ? adminVoiceErrorMessage(voices.error) : null}
        onRetry={() => {
          void voices.refetch();
        }}
        emptyState="No built-in voices match these filters. Sync from the provider to add voices."
        hasNextPage={voices.hasNextPage}
        isFetchingNextPage={voices.isFetchingNextPage}
        fetchNextPage={voices.fetchNextPage}
      />
      {player.state.status === "error" ? (
        <p role="alert" className="text-sm text-destructive">
          {player.state.message}
        </p>
      ) : null}
    </div>
  );
}
