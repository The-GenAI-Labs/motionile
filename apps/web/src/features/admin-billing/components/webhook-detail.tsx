"use client";

import { RotateCwIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { AdminBillingError } from "@/features/admin-billing/components/admin-billing-error";
import { DetailList, DetailSection } from "@/features/admin-billing/components/detail-section";
import { JsonBlock } from "@/features/admin-billing/components/json-block";
import { StatusBadge } from "@/features/admin-billing/components/status-badge";
import { adminBillingErrorMessage } from "@/features/admin-billing/errors";
import {
  useAdminWebhook,
  useReprocessWebhook,
} from "@/features/admin-billing/hooks/use-admin-webhooks";
import type { AdminWebhookEventDetail } from "@/features/admin-billing/types/admin-billing.types";
import { formatDateTime } from "@/lib/utils/format";

const REPROCESSABLE_STATUSES = new Set(["failed", "processed", "ignored"]);

function ReprocessAction({ event }: { event: AdminWebhookEventDetail }) {
  const reprocess = useReprocessWebhook(event.id);
  const [open, setOpen] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  if (!REPROCESSABLE_STATUSES.has(event.status)) {
    return (
      <p className="text-sm text-muted-foreground">
        Only failed, processed or ignored events can be reprocessed. This one is still{" "}
        {event.status}.
      </p>
    );
  }
  return (
    <ConfirmDialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) {
          setFailure(null);
        }
      }}
      trigger={
        <Button variant="outline">
          <RotateCwIcon aria-hidden="true" /> Reprocess
        </Button>
      }
      title="Reprocess this webhook event?"
      description="The event is queued and its handler runs again. Handlers are idempotent, so money and credits are never applied twice, but a failed event may now succeed."
      confirmLabel="Reprocess event"
      error={failure === null ? null : adminBillingErrorMessage(failure)}
      onConfirm={async () => {
        setFailure(null);
        try {
          await reprocess.mutateAsync();
        } catch (error) {
          setFailure(error);
          throw error;
        }
        toast.success("Reprocessing queued");
      }}
    />
  );
}

export function WebhookDetail({ eventId }: { eventId: string }) {
  const event = useAdminWebhook(eventId);
  if (event.isPending) {
    return <Skeleton role="status" aria-label="Loading webhook event" className="h-96" />;
  }
  if (event.isError) {
    return (
      <AdminBillingError
        error={event.error}
        onRetry={() => {
          void event.refetch();
        }}
      />
    );
  }
  const data = event.data;
  return (
    <div className="space-y-6">
      <DetailSection title="Event" actions={<ReprocessAction event={data} />}>
        <StatusBadge status={data.status} />
        <DetailList
          items={[
            { label: "Event type", value: <span className="font-mono">{data.eventType}</span> },
            { label: "Event ID", value: <span className="font-mono">{data.eventId}</span> },
            { label: "Provider", value: data.provider },
            { label: "Attempts", value: <span className="font-mono">{data.attempts}</span> },
            { label: "Received", value: formatDateTime(data.receivedAt) },
            {
              label: "Raised by provider",
              value: data.eventCreatedAt ? formatDateTime(data.eventCreatedAt) : "Unknown",
            },
            {
              label: "Processed",
              value: data.processedAt ? formatDateTime(data.processedAt) : "Not processed",
            },
            ...(data.ignoredReason
              ? [{ label: "Ignored because", value: data.ignoredReason }]
              : []),
          ]}
        />
        {data.lastError ? (
          <p role="note" className="rounded-md border bg-elevated p-3 font-mono text-xs">
            {data.lastError}
          </p>
        ) : null}
      </DetailSection>
      <DetailSection title="Payload">
        <p className="text-sm text-muted-foreground">
          Read-only. Sensitive fields are redacted by the server.
        </p>
        <JsonBlock label="Webhook payload" value={data.payload} />
      </DetailSection>
    </div>
  );
}
