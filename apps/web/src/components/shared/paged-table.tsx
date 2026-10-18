"use client";

import type { ReactNode } from "react";

import { CursorPagination } from "@/components/shared/cursor-pagination";
import { DataTable, type DataTableColumn } from "@/components/shared/data-table";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

interface PagedTableProps<TData extends object> {
  caption: string;
  columns: DataTableColumn<TData>[];
  rows: TData[];
  getRowId: (row: TData, index: number) => string;
  isPending: boolean;
  errorMessage: string | null;
  onRetry: () => void;
  emptyState: ReactNode;
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  fetchNextPage: () => unknown;
}

export function PagedTable<TData extends object>({
  caption,
  columns,
  rows,
  getRowId,
  isPending,
  errorMessage,
  onRetry,
  emptyState,
  hasNextPage,
  isFetchingNextPage,
  fetchNextPage,
}: PagedTableProps<TData>) {
  if (isPending) {
    return (
      <Skeleton role="status" aria-label={`Loading ${caption.toLowerCase()}`} className="h-64" />
    );
  }
  if (errorMessage !== null && rows.length === 0) {
    return (
      <div role="alert" className="flex flex-wrap items-center gap-3 text-sm text-destructive">
        <p>{errorMessage}</p>
        <Button variant="outline" size="sm" onClick={onRetry}>
          Try again
        </Button>
      </div>
    );
  }
  return (
    <DataTable
      caption={caption}
      columns={columns}
      data={rows}
      getRowId={getRowId}
      emptyState={emptyState}
      footer={
        rows.length === 0 ? null : (
          <>
            {errorMessage !== null ? (
              <p role="alert" className="text-center text-sm text-destructive">
                {errorMessage}
              </p>
            ) : null}
            <CursorPagination
              hasNextPage={hasNextPage}
              isFetchingNextPage={isFetchingNextPage}
              fetchNextPage={fetchNextPage}
            />
          </>
        )
      }
    />
  );
}
