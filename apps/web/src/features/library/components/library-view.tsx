"use client";

import { LibraryIcon, SearchXIcon } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { CursorPagination } from "@/components/shared/cursor-pagination";
import { EmptyState } from "@/components/shared/empty-state";
import { FilterPanel, SelectFilter, TextFilter } from "@/components/shared/filter-fields";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { LibraryGrid } from "@/features/library/components/library-grid";
import { LibraryItemDialog } from "@/features/library/components/library-item-dialog";
import { libraryErrorMessage } from "@/features/library/errors";
import { useLibrary } from "@/features/library/hooks/use-library";
import { useLibraryFilters } from "@/features/library/hooks/use-library-filters";
import { ASPECT_ORDER, aspectDescriptions } from "@/features/library/schemas/library.schema";
import { flattenCursorPages } from "@/lib/api/pagination";

const aspectOptions = ASPECT_ORDER.map((aspect) => ({
  value: aspect,
  label: `${aspect} ${aspectDescriptions[aspect].toLowerCase()}`,
}));

export function LibraryView() {
  const { state, setState, filters, active } = useLibraryFilters();
  const library = useLibrary(filters);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const items = flattenCursorPages(library.data?.pages);
  const selected = items.find((item) => item.jobId === selectedId);

  const content = () => {
    if (library.isPending) {
      return (
        <Skeleton
          role="status"
          aria-hidden={false}
          aria-label="Loading your videos"
          className="h-96 w-full"
        />
      );
    }
    if (library.isError && items.length === 0) {
      return (
        <div role="alert" className="flex flex-wrap items-center gap-3 text-sm text-destructive">
          <p>{libraryErrorMessage(library.error)}</p>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              void library.refetch();
            }}
          >
            Try again
          </Button>
        </div>
      );
    }
    if (items.length === 0) {
      return active ? (
        <EmptyState
          icon={SearchXIcon}
          title="No videos match"
          description="Try a different search or clear the filters."
          action={
            <Button
              variant="outline"
              onClick={() => {
                void setState(null);
              }}
            >
              Clear filters
            </Button>
          }
        />
      ) : (
        <EmptyState
          icon={LibraryIcon}
          title="No videos yet"
          description="Videos you create appear here once they are finished."
          action={
            <Button asChild>
              <Link href="/create">Create your first video</Link>
            </Button>
          }
        />
      );
    }
    return (
      <div className="space-y-2">
        <LibraryGrid
          items={items}
          hasNextPage={library.hasNextPage}
          isFetchingNextPage={library.isFetchingNextPage}
          fetchNextPage={library.fetchNextPage}
          onOpen={setSelectedId}
        />
        {library.isError ? (
          <p role="alert" className="text-center text-sm text-destructive">
            {libraryErrorMessage(library.error)}
          </p>
        ) : null}
        <CursorPagination
          hasNextPage={library.hasNextPage}
          isFetchingNextPage={library.isFetchingNextPage}
          fetchNextPage={library.fetchNextPage}
          loadMoreLabel="Load more videos"
          endLabel="You have reached the end of your library."
        />
      </div>
    );
  };

  return (
    <div className="space-y-6">
      <FilterPanel
        label="Library filters"
        onClear={() => {
          void setState(null);
        }}
      >
        <TextFilter
          id="library-search"
          label="Search videos"
          type="search"
          placeholder="Search by title or topic"
          value={state.q}
          onChange={(value) => void setState({ q: value || null })}
        />
        <SelectFilter
          id="library-aspect"
          label="Aspect ratio"
          value={state.aspect ?? ""}
          options={aspectOptions}
          onChange={(value) => {
            const aspect = ASPECT_ORDER.find((candidate) => candidate === value);
            void setState({ aspect: aspect ?? null });
          }}
        />
      </FilterPanel>
      {content()}
      <LibraryItemDialog
        item={selected}
        onClose={() => {
          setSelectedId(null);
        }}
      />
    </div>
  );
}
