"use client";

import { DownloadIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { AdminBillingError } from "@/features/admin-billing/components/admin-billing-error";
import { DetailList, DetailSection } from "@/features/admin-billing/components/detail-section";
import { JsonBlock } from "@/features/admin-billing/components/json-block";
import { StatusBadge } from "@/features/admin-billing/components/status-badge";
import {
  useAdminRun,
  useDownloadReport,
} from "@/features/admin-billing/hooks/use-admin-reconciliation";
import { runTypeLabels } from "@/features/admin-billing/schemas/admin-billing.schema";
import type { AdminRun } from "@/features/admin-billing/types/admin-billing.types";
import { formatCredits, formatDateTime } from "@/lib/utils/format";

function ReportDownload({ run }: { run: AdminRun }) {
  const download = useDownloadReport(run.id);
  if (!run.hasReport) {
    return <p className="text-sm text-muted-foreground">No report was stored for this run.</p>;
  }
  return (
    <div className="flex flex-col items-end gap-2">
      <Button
        variant="outline"
        disabled={download.isPending}
        aria-busy={download.isPending}
        onClick={() => {
          download.mutate();
        }}
      >
        <DownloadIcon aria-hidden="true" /> Download report
      </Button>
      {download.isError ? <AdminBillingError error={download.error} /> : null}
    </div>
  );
}

export function RunDetail({ runId }: { runId: string }) {
  const run = useAdminRun(runId);
  if (run.isPending) {
    return <Skeleton role="status" aria-label="Loading reconciliation run" className="h-96" />;
  }
  if (run.isError) {
    return (
      <AdminBillingError
        error={run.error}
        onRetry={() => {
          void run.refetch();
        }}
      />
    );
  }
  const data = run.data;
  return (
    <div className="space-y-6">
      <DetailSection title={runTypeLabels[data.type]} actions={<ReportDownload run={data} />}>
        <StatusBadge status={data.status} />
        <DetailList
          items={[
            { label: "Started", value: formatDateTime(data.startedAt) },
            {
              label: "Finished",
              value: data.finishedAt ? formatDateTime(data.finishedAt) : "Still running",
            },
            {
              label: "Period",
              value:
                data.periodStart && data.periodEnd
                  ? `${formatDateTime(data.periodStart)} to ${formatDateTime(data.periodEnd)}`
                  : "Not applicable",
            },
            {
              label: "Checked",
              value: <span className="font-mono">{formatCredits(data.checkedCount)}</span>,
            },
            {
              label: "Mismatches",
              value: <span className="font-mono">{formatCredits(data.mismatchCount)}</span>,
            },
            {
              label: "Repaired",
              value: <span className="font-mono">{formatCredits(data.repairedCount)}</span>,
            },
          ]}
        />
        {data.error ? (
          <p role="alert" className="rounded-md border p-3 font-mono text-xs text-destructive">
            {data.error}
          </p>
        ) : null}
        {data.mismatchCount > 0 ? (
          <p role="note" className="rounded-md border bg-elevated p-3 text-sm">
            This run found differences between Razorpay and our records. Download the report to see
            each one, then review the affected payments and orders.
          </p>
        ) : null}
      </DetailSection>
      <DetailSection title="Summary">
        <JsonBlock label="Run summary" value={data.summary} />
      </DetailSection>
    </div>
  );
}
