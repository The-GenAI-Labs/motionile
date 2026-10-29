"use client";

import { useVirtualizer } from "@tanstack/react-virtual";
import { useEffect, useState } from "react";

import { LibraryCard } from "@/features/library/components/library-card";
import { useColumnCount } from "@/features/library/hooks/use-column-count";
import type { LibraryItem } from "@/features/library/types/library.types";

export const ESTIMATED_ROW_HEIGHT = 380;
const GRID_HEIGHT = "min(70dvh, 56rem)";
const OVERSCAN_ROWS = 2;

interface LibraryGridProps {
  items: readonly LibraryItem[];
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  fetchNextPage: () => unknown;
  onOpen: (jobId: string) => void;
}

export function LibraryGrid({
  items,
  hasNextPage,
  isFetchingNextPage,
  fetchNextPage,
  onOpen,
}: LibraryGridProps) {
  "use no memo";
  const [scroller, setScroller] = useState<HTMLDivElement | null>(null);
  const columns = useColumnCount(scroller);
  const rowCount = Math.ceil(items.length / columns);
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: rowCount,
    getScrollElement: () => scroller,
    estimateSize: () => ESTIMATED_ROW_HEIGHT,
    getItemKey: (index) => items[index * columns]?.jobId ?? index,
    overscan: OVERSCAN_ROWS,
  });
  const virtualRows = virtualizer.getVirtualItems();
  const lastRenderedRow = virtualRows.at(-1)?.index ?? -1;

  useEffect(() => {
    if (hasNextPage && !isFetchingNextPage && rowCount > 0 && lastRenderedRow >= rowCount - 1) {
      void fetchNextPage();
    }
  }, [hasNextPage, isFetchingNextPage, rowCount, lastRenderedRow, fetchNextPage]);

  return (
    <div
      ref={setScroller}
      role="region"
      aria-label="Your videos"
      tabIndex={0}
      style={{ height: GRID_HEIGHT }}
      className="overflow-auto rounded-lg focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none"
    >
      <div
        role="list"
        aria-label="Videos"
        className="relative w-full"
        style={{ height: virtualizer.getTotalSize() }}
      >
        {virtualRows.map((virtualRow) => {
          const rowItems = items.slice(
            virtualRow.index * columns,
            virtualRow.index * columns + columns,
          );
          return (
            <div
              key={virtualRow.key}
              role="presentation"
              data-index={virtualRow.index}
              ref={virtualizer.measureElement}
              className="absolute top-0 left-0 grid w-full gap-4 pb-4"
              style={{
                transform: `translateY(${String(virtualRow.start)}px)`,
                gridTemplateColumns: `repeat(${String(columns)}, minmax(0, 1fr))`,
              }}
            >
              {rowItems.map((item) => (
                <div key={item.jobId} role="listitem" className="min-w-0">
                  <LibraryCard item={item} onOpen={onOpen} />
                </div>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}
