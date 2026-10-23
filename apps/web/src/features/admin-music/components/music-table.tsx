"use client";

import { createDataTableColumnHelper } from "@/components/shared/data-table";
import {
  BOOLEAN_OPTIONS,
  booleanFromValue,
  FilterPanel,
  SelectFilter,
  TextFilter,
  valueFromBoolean,
} from "@/components/shared/filter-fields";
import { PagedTable } from "@/components/shared/paged-table";
import { Badge } from "@/components/ui/badge";
import { EditTrackDialog } from "@/features/admin-music/components/edit-track-dialog";
import { TrackActiveToggle } from "@/features/admin-music/components/track-active-toggle";
import { TrackPreview } from "@/features/admin-music/components/track-preview";
import { adminMusicErrorMessage } from "@/features/admin-music/errors";
import {
  toMusicFilters,
  useMusicFilterState,
} from "@/features/admin-music/hooks/use-music-filters";
import { useMusicTracks } from "@/features/admin-music/hooks/use-music-tracks";
import { isSecureLicenseUrl } from "@/features/admin-music/schemas/admin-music.schema";
import type { MusicTrack } from "@/features/admin-music/types/admin-music.types";
import { flattenCursorPages } from "@/lib/api/pagination";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";
import { formatDate, formatDurationMs } from "@/lib/utils/format";

const FILTER_DEBOUNCE_MS = 300;

const column = createDataTableColumnHelper<MusicTrack>();

const columns = [
  column.display({
    id: "title",
    header: "Title",
    cell: ({ row }) => (
      <div className="flex max-w-64 flex-col">
        <span className="truncate font-medium">{row.original.title}</span>
        {row.original.attributionText ? (
          <span className="truncate text-xs text-muted-foreground">
            {row.original.attributionText}
          </span>
        ) : null}
      </div>
    ),
  }),
  column.display({
    id: "mood",
    header: "Mood",
    cell: ({ row }) => <span className="font-mono">{row.original.mood}</span>,
  }),
  column.display({
    id: "bpm",
    header: "BPM",
    cell: ({ row }) => <span className="font-mono">{row.original.bpm ?? "-"}</span>,
  }),
  column.display({
    id: "duration",
    header: "Duration",
    cell: ({ row }) => (
      <span className="font-mono">{formatDurationMs(row.original.durationMs)}</span>
    ),
  }),
  column.display({
    id: "license",
    header: "License",
    cell: ({ row }) =>
      isSecureLicenseUrl(row.original.licenseUrl) ? (
        <a
          href={row.original.licenseUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="rounded-sm underline underline-offset-4 focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none"
        >
          {row.original.licenseName}
        </a>
      ) : (
        row.original.licenseName
      ),
  }),
  column.display({
    id: "status",
    header: "Status",
    cell: ({ row }) => (
      <Badge variant={row.original.isActive ? "success" : "outline"}>
        {row.original.isActive ? "Active" : "Inactive"}
      </Badge>
    ),
  }),
  column.display({
    id: "uploaded",
    header: "Uploaded",
    cell: ({ row }) => formatDate(row.original.createdAt),
  }),
  column.display({
    id: "preview",
    header: "Preview",
    cell: ({ row }) => <TrackPreview track={row.original} />,
  }),
  column.display({
    id: "actions",
    header: () => <span className="sr-only">Actions</span>,
    cell: ({ row }) => (
      <div className="flex gap-2">
        <EditTrackDialog track={row.original} />
        <TrackActiveToggle track={row.original} />
      </div>
    ),
  }),
];

export function MusicTable() {
  const [state, setState] = useMusicFilterState();
  const mood = useDebouncedValue(state.mood, FILTER_DEBOUNCE_MS);
  const tracks = useMusicTracks(toMusicFilters(state, mood));
  return (
    <div className="space-y-5">
      <FilterPanel
        label="Music filters"
        onClear={() => {
          void setState(null);
        }}
      >
        <TextFilter
          id="music-mood"
          label="Mood"
          type="search"
          placeholder="For example calm"
          value={state.mood}
          onChange={(value) => void setState({ mood: value || null })}
        />
        <SelectFilter
          id="music-active"
          label="Active"
          value={valueFromBoolean(state.active)}
          options={BOOLEAN_OPTIONS}
          onChange={(value) => void setState({ active: booleanFromValue(value) })}
        />
      </FilterPanel>
      <PagedTable
        caption="Music tracks"
        columns={columns}
        rows={flattenCursorPages(tracks.data?.pages)}
        getRowId={(track) => track.id}
        isPending={tracks.isPending}
        errorMessage={tracks.isError ? adminMusicErrorMessage(tracks.error) : null}
        onRetry={() => {
          void tracks.refetch();
        }}
        emptyState="No music tracks match these filters."
        hasNextPage={tracks.hasNextPage}
        isFetchingNextPage={tracks.isFetchingNextPage}
        fetchNextPage={tracks.fetchNextPage}
      />
    </div>
  );
}
