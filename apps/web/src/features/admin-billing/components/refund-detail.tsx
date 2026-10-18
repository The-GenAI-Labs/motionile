"use client";

import Link from "next/link";

import { Skeleton } from "@/components/ui/skeleton";
import { AdminBillingError } from "@/features/admin-billing/components/admin-billing-error";
import { DetailList, DetailSection } from "@/features/admin-billing/components/detail-section";
import { StatusBadge } from "@/features/admin-billing/components/status-badge";
import { useAdminRefund } from "@/features/admin-billing/hooks/use-admin-payments";
import { adminBillingPaths } from "@/features/admin-billing/paths";
import { formatCredits, formatDateTime, formatPaise } from "@/lib/utils/format";

export function RefundDetail({ refundId }: { refundId: string }) {
  const refund = useAdminRefund(refundId);
  if (refund.isPending) {
    return <Skeleton role="status" aria-label="Loading refund" className="h-72" />;
  }
  if (refund.isError) {
    return (
      <AdminBillingError
        error={refund.error}
        onRetry={() => {
          void refund.refetch();
        }}
      />
    );
  }
  const data = refund.data;
  return (
    <DetailSection title="Refund">
      <StatusBadge status={data.status} />
      <DetailList
        items={[
          {
            label: "Razorpay refund",
            value: <span className="font-mono">{data.razorpayRefundId ?? "Not created yet"}</span>,
          },
          {
            label: "Refund amount",
            value: <span className="font-mono">{formatPaise(data.amountPaise)}</span>,
          },
          {
            label: "Payment amount (incl. GST)",
            value: <span className="font-mono">{formatPaise(data.paymentAmountPaise)}</span>,
          },
          {
            label: "Credits clawed back",
            value: <span className="font-mono">{formatCredits(data.creditsClawedBack)}</span>,
          },
          { label: "Created", value: formatDateTime(data.createdAt) },
          {
            label: "Processed",
            value: data.processedAt ? formatDateTime(data.processedAt) : "Not processed",
          },
          {
            label: "Payment",
            value: (
              <Link
                href={adminBillingPaths.payment(data.paymentId)}
                className="font-mono text-xs hover:underline"
              >
                {data.paymentId}
              </Link>
            ),
          },
          {
            label: "User",
            value: (
              <Link
                href={adminBillingPaths.user(data.userId)}
                className="font-mono text-xs hover:underline"
              >
                {data.userId}
              </Link>
            ),
          },
          { label: "Reason", value: data.reason },
          ...(data.failureReason ? [{ label: "Failure", value: data.failureReason }] : []),
        ]}
      />
    </DetailSection>
  );
}
