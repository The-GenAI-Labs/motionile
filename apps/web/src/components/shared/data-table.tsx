"use client";

import {
  type ColumnDef,
  createColumnHelper,
  type RowData,
  tableFeatures,
  useTable,
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { type ReactNode, useRef } from "react";

import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils/cn";

export const dataTableFeatures = tableFeatures({});

export type DataTableFeatures = typeof dataTableFeatures;

export type DataTableColumn<TData extends RowData> = ColumnDef<DataTableFeatures, TData>;

export const createDataTableColumnHelper = <TData extends RowData>() =>
  createColumnHelper<DataTableFeatures, TData>();

export const DEFAULT_ROW_HEIGHT = 44;
export const DEFAULT_MAX_HEIGHT = 560;
const OVERSCAN_ROWS = 8;

interface DataTableProps<TData extends RowData> {
  caption: string;
  columns: DataTableColumn<TData>[];
  data: TData[];
  getRowId: (row: TData, index: number) => string;
  emptyState?: ReactNode;
  footer?: ReactNode;
  estimateRowHeight?: number;
  maxHeight?: number;
  className?: string;
}

export function DataTable<TData extends RowData>({
  caption,
  columns,
  data,
  getRowId,
  emptyState = "No results.",
  footer,
  estimateRowHeight = DEFAULT_ROW_HEIGHT,
  maxHeight = DEFAULT_MAX_HEIGHT,
  className,
}: DataTableProps<TData>) {
  "use no memo";
  const scrollRef = useRef<HTMLDivElement>(null);
  const table = useTable({ features: dataTableFeatures, columns, data, getRowId });
  const rows = table.getRowModel().rows;
  const columnCount = table.getAllLeafColumns().length;
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => estimateRowHeight,
    getItemKey: (index) => rows[index]?.id ?? index,
    overscan: OVERSCAN_ROWS,
  });
  const virtualRows = virtualizer.getVirtualItems();
  const paddingTop = virtualRows[0]?.start ?? 0;
  const paddingBottom =
    virtualRows.length > 0 ? virtualizer.getTotalSize() - (virtualRows.at(-1)?.end ?? 0) : 0;

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <div
        ref={scrollRef}
        role="region"
        aria-label={caption}
        tabIndex={0}
        style={{ maxHeight }}
        className="overflow-auto rounded-lg border focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none"
      >
        <Table aria-rowcount={rows.length + 1}>
          <TableCaption className="sr-only">{caption}</TableCaption>
          <TableHeader className="sticky top-0 z-10 bg-surface">
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id} aria-rowindex={1}>
                {headerGroup.headers.map((header) => (
                  <TableHead key={header.id} scope="col" colSpan={header.colSpan}>
                    {header.isPlaceholder ? null : <table.FlexRender header={header} />}
                  </TableHead>
                ))}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {rows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={columnCount} className="h-24 text-center text-muted-foreground">
                  {emptyState}
                </TableCell>
              </TableRow>
            ) : null}
            {paddingTop > 0 ? (
              <tr aria-hidden="true">
                <td colSpan={columnCount} style={{ height: paddingTop, padding: 0 }} />
              </tr>
            ) : null}
            {virtualRows.map((virtualRow) => {
              const row = rows[virtualRow.index];
              if (row === undefined) {
                return null;
              }
              return (
                <TableRow
                  key={row.id}
                  data-index={virtualRow.index}
                  ref={virtualizer.measureElement}
                  aria-rowindex={virtualRow.index + 2}
                >
                  {row.getAllCells().map((cell) => (
                    <TableCell key={cell.id}>
                      <table.FlexRender cell={cell} />
                    </TableCell>
                  ))}
                </TableRow>
              );
            })}
            {paddingBottom > 0 ? (
              <tr aria-hidden="true">
                <td colSpan={columnCount} style={{ height: paddingBottom, padding: 0 }} />
              </tr>
            ) : null}
          </TableBody>
        </Table>
      </div>
      {footer}
    </div>
  );
}
