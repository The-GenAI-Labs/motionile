"use client";

import { zProductKindName } from "@motionile/api-contract";
import { PlusIcon } from "lucide-react";
import Link from "next/link";

import { createDataTableColumnHelper } from "@/components/shared/data-table";
import { PagedTable } from "@/components/shared/paged-table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  BOOLEAN_OPTIONS,
  booleanFromValue,
  FilterPanel,
  optionsFromValues,
  SelectFilter,
  TextFilter,
  valueFromBoolean,
} from "@/features/admin-billing/components/filter-fields";
import { adminBillingErrorMessage } from "@/features/admin-billing/errors";
import {
  toProductFilters,
  useProductFilterState,
} from "@/features/admin-billing/hooks/use-admin-billing-filters";
import { useAdminProducts } from "@/features/admin-billing/hooks/use-admin-products";
import { adminBillingPaths } from "@/features/admin-billing/paths";
import {
  intervalLabels,
  productKindLabels,
} from "@/features/admin-billing/schemas/admin-billing.schema";
import type { AdminProduct } from "@/features/admin-billing/types/admin-billing.types";
import { usePermissions } from "@/features/auth/hooks/use-permissions";
import { flattenCursorPages } from "@/lib/api/pagination";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";
import { formatCredits, formatPaise } from "@/lib/utils/format";

const SEARCH_DEBOUNCE_MS = 300;

const column = createDataTableColumnHelper<AdminProduct>();

const columns = [
  column.display({
    id: "name",
    header: "Product",
    cell: ({ row }) => (
      <div className="flex flex-col">
        <Link
          href={adminBillingPaths.product(row.original.id)}
          className="font-medium hover:underline"
        >
          {row.original.name}
        </Link>
        <span className="font-mono text-xs text-muted-foreground">{row.original.code}</span>
      </div>
    ),
  }),
  column.display({
    id: "kind",
    header: "Kind",
    cell: ({ row }) => productKindLabels[row.original.kind],
  }),
  column.display({
    id: "plan",
    header: "Plan",
    cell: ({ row }) =>
      row.original.interval && row.original.planKey ? (
        <span>
          <span className="font-mono">{row.original.planKey}</span>{" "}
          {intervalLabels[row.original.interval].toLowerCase()}
        </span>
      ) : (
        "-"
      ),
  }),
  column.display({
    id: "price",
    header: "Price (incl. GST)",
    cell: ({ row }) => <span className="font-mono">{formatPaise(row.original.pricePaise)}</span>,
  }),
  column.display({
    id: "credits",
    header: "Credits",
    cell: ({ row }) => (
      <span className="font-mono">{formatCredits(row.original.creditsGranted)}</span>
    ),
  }),
  column.display({
    id: "state",
    header: "State",
    cell: ({ row }) => (
      <div className="flex flex-wrap gap-1">
        <Badge variant={row.original.isActive ? "success" : "outline"}>
          {row.original.isActive ? "Active" : "Inactive"}
        </Badge>
        {row.original.isSample ? <Badge variant="outline">Sample</Badge> : null}
        {row.original.isUsed ? <Badge variant="outline">In use</Badge> : null}
      </div>
    ),
  }),
  column.display({
    id: "version",
    header: "Version",
    cell: ({ row }) => <span className="font-mono">v{row.original.version}</span>,
  }),
];

export function ProductsTable() {
  const [state, setState] = useProductFilterState();
  const search = useDebouncedValue(state.q, SEARCH_DEBOUNCE_MS);
  const products = useAdminProducts(toProductFilters(state, search));
  const { can } = usePermissions();
  return (
    <div className="space-y-5">
      <div className="flex justify-end">
        {can("billing.products.manage") ? (
          <Button asChild>
            <Link href={adminBillingPaths.newProduct}>
              <PlusIcon aria-hidden="true" /> New product
            </Link>
          </Button>
        ) : null}
      </div>
      <FilterPanel
        label="Product filters"
        onClear={() => {
          void setState(null);
        }}
      >
        <TextFilter
          id="product-search"
          label="Search"
          type="search"
          placeholder="Name or code"
          value={state.q}
          onChange={(value) => void setState({ q: value || null })}
        />
        <SelectFilter
          id="product-kind"
          label="Kind"
          value={state.kind ?? ""}
          options={optionsFromValues(zProductKindName.options, productKindLabels)}
          onChange={(value) => {
            const kind = zProductKindName.safeParse(value);
            void setState({ kind: kind.success ? kind.data : null });
          }}
        />
        <SelectFilter
          id="product-active"
          label="Active"
          value={valueFromBoolean(state.active)}
          options={BOOLEAN_OPTIONS}
          onChange={(value) => void setState({ active: booleanFromValue(value) })}
        />
        <SelectFilter
          id="product-sample"
          label="Sample"
          value={valueFromBoolean(state.sample)}
          options={BOOLEAN_OPTIONS}
          onChange={(value) => void setState({ sample: booleanFromValue(value) })}
        />
      </FilterPanel>
      <PagedTable
        caption="Products"
        columns={columns}
        rows={flattenCursorPages(products.data?.pages)}
        getRowId={(product) => product.id}
        isPending={products.isPending}
        errorMessage={products.isError ? adminBillingErrorMessage(products.error) : null}
        onRetry={() => {
          void products.refetch();
        }}
        emptyState="No products match these filters."
        hasNextPage={products.hasNextPage}
        isFetchingNextPage={products.isFetchingNextPage}
        fetchNextPage={products.fetchNextPage}
      />
    </div>
  );
}
