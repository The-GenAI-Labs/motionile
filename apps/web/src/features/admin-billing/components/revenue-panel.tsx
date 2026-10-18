"use client";

import { createDataTableColumnHelper, DataTable } from "@/components/shared/data-table";
import { Skeleton } from "@/components/ui/skeleton";
import { AdminBillingError } from "@/features/admin-billing/components/admin-billing-error";
import { DailyBarChart } from "@/features/admin-billing/components/daily-bar-chart";
import { DetailSection } from "@/features/admin-billing/components/detail-section";
import { useRevenueAnalytics } from "@/features/admin-billing/hooks/use-admin-analytics";
import type {
  DateRange,
  RevenueAnalytics,
} from "@/features/admin-billing/types/admin-billing.types";
import { formatCredits, formatPaise, formatSignedPaise } from "@/lib/utils/format";

type RevenueDay = RevenueAnalytics["days"][number];

const column = createDataTableColumnHelper<RevenueDay>();

const columns = [
  column.display({ id: "date", header: "Date", cell: ({ row }) => row.original.date }),
  column.display({
    id: "captured",
    header: "Captured",
    cell: ({ row }) => <span className="font-mono">{formatPaise(row.original.capturedPaise)}</span>,
  }),
  column.display({
    id: "refunded",
    header: "Refunded",
    cell: ({ row }) => <span className="font-mono">{formatPaise(row.original.refundedPaise)}</span>,
  }),
  column.display({
    id: "net",
    header: "Net",
    cell: ({ row }) => (
      <span className="font-mono">{formatSignedPaise(row.original.netPaise)}</span>
    ),
  }),
  column.display({
    id: "payments",
    header: "Payments",
    cell: ({ row }) => <span className="font-mono">{row.original.paymentCount}</span>,
  }),
];

export function RevenueView({ data }: { data: RevenueAnalytics }) {
  const totals = [
    { label: "Captured", value: formatPaise(data.totals.capturedPaise) },
    { label: "Refunded", value: formatPaise(data.totals.refundedPaise) },
    { label: "Net", value: formatSignedPaise(data.totals.netPaise) },
    { label: "Payments", value: formatCredits(data.totals.paymentCount) },
  ];
  return (
    <div className="space-y-5">
      <dl className="grid gap-4 sm:grid-cols-4">
        {totals.map((total) => (
          <div key={total.label}>
            <dt className="text-sm text-muted-foreground">{total.label}</dt>
            <dd className="font-mono text-2xl font-semibold">{total.value}</dd>
          </div>
        ))}
      </dl>
      <p className="text-sm text-muted-foreground">
        {data.currency} amounts include GST. {data.rangeStart} to {data.rangeEnd}.
      </p>
      <DailyBarChart
        title="Revenue per day"
        days={data.days.map((day) => day.date)}
        formatValue={formatPaise}
        series={[
          {
            key: "captured",
            label: "Captured",
            swatchClassName: "bg-foreground",
            barClassName: "fill-foreground",
            values: data.days.map((day) => day.capturedPaise),
          },
          {
            key: "refunded",
            label: "Refunded",
            swatchClassName: "bg-muted-foreground",
            barClassName: "fill-muted-foreground",
            values: data.days.map((day) => day.refundedPaise),
          },
        ]}
      />
      <DataTable
        caption="Revenue per day"
        columns={columns}
        data={[...data.days].reverse()}
        getRowId={(day) => day.date}
        maxHeight={360}
      />
    </div>
  );
}

export function RevenuePanel({ range }: { range: DateRange }) {
  const revenue = useRevenueAnalytics(range);
  return (
    <DetailSection title="Revenue">
      {revenue.isPending ? (
        <Skeleton role="status" aria-label="Loading revenue" className="h-64" />
      ) : revenue.isError ? (
        <AdminBillingError
          error={revenue.error}
          onRetry={() => {
            void revenue.refetch();
          }}
        />
      ) : (
        <RevenueView data={revenue.data} />
      )}
    </DetailSection>
  );
}
