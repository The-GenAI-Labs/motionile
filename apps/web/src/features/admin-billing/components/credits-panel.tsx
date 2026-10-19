"use client";

import { createDataTableColumnHelper, DataTable } from "@/components/shared/data-table";
import { Skeleton } from "@/components/ui/skeleton";
import { AdminBillingError } from "@/features/admin-billing/components/admin-billing-error";
import { DailyBarChart } from "@/features/admin-billing/components/daily-bar-chart";
import { DetailSection } from "@/features/admin-billing/components/detail-section";
import { useCreditsAnalytics } from "@/features/admin-billing/hooks/use-admin-analytics";
import type {
  CreditsAnalytics,
  DateRange,
} from "@/features/admin-billing/types/admin-billing.types";
import { lotSourceLabels } from "@/features/credits/schemas/credits.schema";
import { formatCredits } from "@/lib/utils/format";

type CreditsDay = CreditsAnalytics["days"][number];

const column = createDataTableColumnHelper<CreditsDay>();

const numberCell = (value: number) => <span className="font-mono">{formatCredits(value)}</span>;

const columns = [
  column.display({ id: "date", header: "Date", cell: ({ row }) => row.original.date }),
  column.display({
    id: "granted",
    header: "Granted",
    cell: ({ row }) => numberCell(row.original.grantedTotal),
  }),
  column.display({
    id: "consumed",
    header: "Consumed",
    cell: ({ row }) => numberCell(row.original.consumed),
  }),
  column.display({
    id: "expired",
    header: "Expired",
    cell: ({ row }) => numberCell(row.original.expired),
  }),
  column.display({
    id: "clawedBack",
    header: "Clawed back",
    cell: ({ row }) => numberCell(row.original.clawedBack),
  }),
  column.display({
    id: "adjustedDown",
    header: "Deducted by admins",
    cell: ({ row }) => numberCell(row.original.adjustedDown),
  }),
];

const GRANT_SOURCES = ["purchase", "subscription", "admin", "promo"] as const;

export function CreditsView({ data }: { data: CreditsAnalytics }) {
  const totals = [
    { label: "Granted", value: data.totals.grantedTotal },
    { label: "Consumed", value: data.totals.consumed },
    { label: "Expired", value: data.totals.expired },
    { label: "Clawed back", value: data.totals.clawedBack },
    { label: "Deducted by admins", value: data.totals.adjustedDown },
  ];
  return (
    <div className="space-y-5">
      <dl className="grid gap-4 sm:grid-cols-3 lg:grid-cols-5">
        {totals.map((total) => (
          <div key={total.label}>
            <dt className="text-sm text-muted-foreground">{total.label}</dt>
            <dd className="font-mono text-2xl font-semibold">{formatCredits(total.value)}</dd>
          </div>
        ))}
      </dl>
      <p className="text-sm text-muted-foreground">
        Granted by source:{" "}
        {GRANT_SOURCES.map(
          (source) =>
            `${lotSourceLabels[source].toLowerCase()} ${formatCredits(data.totals.granted[source])}`,
        ).join(", ")}
        . Across {formatCredits(data.wallets)} wallets, {formatCredits(data.balance)} credits are
        held and {formatCredits(data.reserved)} are reserved.
      </p>
      <DailyBarChart
        title="Credits granted and consumed per day"
        days={data.days.map((day) => day.date)}
        formatValue={formatCredits}
        series={[
          {
            key: "granted",
            label: "Granted",
            swatchClassName: "bg-foreground",
            barClassName: "fill-foreground",
            values: data.days.map((day) => day.grantedTotal),
          },
          {
            key: "consumed",
            label: "Consumed",
            swatchClassName: "bg-muted-foreground",
            barClassName: "fill-muted-foreground",
            values: data.days.map((day) => day.consumed),
          },
        ]}
      />
      <DataTable
        caption="Credits per day"
        columns={columns}
        data={[...data.days].reverse()}
        getRowId={(day) => day.date}
        maxHeight={360}
      />
    </div>
  );
}

export function CreditsPanel({ range }: { range: DateRange }) {
  const credits = useCreditsAnalytics(range);
  return (
    <DetailSection title="Credits granted and consumed">
      {credits.isPending ? (
        <Skeleton role="status" aria-label="Loading credits" className="h-64" />
      ) : credits.isError ? (
        <AdminBillingError
          error={credits.error}
          onRetry={() => {
            void credits.refetch();
          }}
        />
      ) : (
        <CreditsView data={credits.data} />
      )}
    </DetailSection>
  );
}
