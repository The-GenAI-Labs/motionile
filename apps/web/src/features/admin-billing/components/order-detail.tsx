"use client";

import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { AdminBillingError } from "@/features/admin-billing/components/admin-billing-error";
import { DetailList, DetailSection } from "@/features/admin-billing/components/detail-section";
import { StatusBadge } from "@/features/admin-billing/components/status-badge";
import { useAdminOrder } from "@/features/admin-billing/hooks/use-admin-payments";
import { adminBillingPaths } from "@/features/admin-billing/paths";
import {
  flagGuidance,
  flagReasonLabels,
  productKindLabels,
} from "@/features/admin-billing/schemas/admin-billing.schema";
import type { AdminOrderDetail } from "@/features/admin-billing/types/admin-billing.types";
import { usePermissions } from "@/features/auth/hooks/use-permissions";
import { formatCredits, formatDateTime, formatPaise } from "@/lib/utils/format";

function FlagReview({ order }: { order: AdminOrderDetail }) {
  const { can } = usePermissions();
  if (order.flagReason === null) {
    return null;
  }
  return (
    <DetailSection title="Needs review">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="destructive">{flagReasonLabels[order.flagReason]}</Badge>
        {order.flaggedAt ? (
          <span className="text-sm text-muted-foreground">
            Flagged on {formatDateTime(order.flaggedAt)}
          </span>
        ) : null}
      </div>
      <p className="text-sm">{flagGuidance[order.flagReason]}</p>
      {can("billing.refunds.create") ? null : (
        <p className="text-sm text-muted-foreground">
          Refunding needs the billing.refunds.create permission, which your account does not have.
        </p>
      )}
    </DetailSection>
  );
}

function OrderPayments({ order }: { order: AdminOrderDetail }) {
  if (order.payments.length === 0) {
    return <p className="text-sm text-muted-foreground">No payment has been recorded yet.</p>;
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead scope="col">Payment</TableHead>
          <TableHead scope="col">Status</TableHead>
          <TableHead scope="col">Amount (incl. GST)</TableHead>
          <TableHead scope="col">Refunded</TableHead>
          <TableHead scope="col">Credits</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {order.payments.map((payment) => (
          <TableRow key={payment.id}>
            <TableCell>
              <Link
                href={adminBillingPaths.payment(payment.id)}
                className="font-mono text-xs hover:underline"
              >
                {payment.razorpayPaymentId}
              </Link>
            </TableCell>
            <TableCell>
              <div className="flex flex-wrap gap-1">
                <StatusBadge status={payment.status} />
                {payment.flagged ? <Badge variant="destructive">Flagged</Badge> : null}
              </div>
            </TableCell>
            <TableCell className="font-mono">{formatPaise(payment.amountPaise)}</TableCell>
            <TableCell className="font-mono">{formatPaise(payment.refundedPaise)}</TableCell>
            <TableCell className="font-mono">{formatCredits(payment.creditsGranted)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

export function OrderDetail({ orderId }: { orderId: string }) {
  const order = useAdminOrder(orderId);
  if (order.isPending) {
    return <Skeleton role="status" aria-label="Loading order" className="h-96" />;
  }
  if (order.isError) {
    return (
      <AdminBillingError
        error={order.error}
        onRetry={() => {
          void order.refetch();
        }}
      />
    );
  }
  const data = order.data;
  return (
    <div className="space-y-6">
      <FlagReview order={data} />
      <DetailSection title="Order">
        <div className="flex flex-wrap gap-2">
          <StatusBadge status={data.status} />
          <Badge variant="outline">{productKindLabels[data.kind]}</Badge>
        </div>
        <DetailList
          items={[
            { label: "Receipt", value: <span className="font-mono">{data.receipt}</span> },
            {
              label: "Razorpay order",
              value: <span className="font-mono">{data.razorpayOrderId ?? "Not created"}</span>,
            },
            {
              label: "Product",
              value: (
                <Link href={adminBillingPaths.product(data.productId)} className="hover:underline">
                  {data.productName} (v{data.productVersion})
                </Link>
              ),
            },
            {
              label: "Amount (incl. GST)",
              value: <span className="font-mono">{formatPaise(data.amountPaise)}</span>,
            },
            {
              label: "Credits",
              value: <span className="font-mono">{formatCredits(data.creditsGranted)}</span>,
            },
            { label: "Created", value: formatDateTime(data.createdAt) },
            { label: "Expires", value: formatDateTime(data.expiresAt) },
            { label: "Paid", value: data.paidAt ? formatDateTime(data.paidAt) : "Not paid" },
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
            ...(data.subscriptionId
              ? [
                  {
                    label: "Subscription",
                    value: (
                      <Link
                        href={adminBillingPaths.subscription(data.subscriptionId)}
                        className="font-mono text-xs hover:underline"
                      >
                        {data.subscriptionId}
                      </Link>
                    ),
                  },
                ]
              : []),
            ...(data.failureReason ? [{ label: "Failure", value: data.failureReason }] : []),
          ]}
        />
      </DetailSection>
      <DetailSection title="Payments">
        <OrderPayments order={data} />
      </DetailSection>
    </div>
  );
}
