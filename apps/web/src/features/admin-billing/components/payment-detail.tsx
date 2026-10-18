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
import { RefundDialog } from "@/features/admin-billing/components/refund-dialog";
import { StatusBadge } from "@/features/admin-billing/components/status-badge";
import { useAdminPayment } from "@/features/admin-billing/hooks/use-admin-payments";
import { adminBillingPaths } from "@/features/admin-billing/paths";
import {
  flagReasonLabels,
  intervalLabels,
} from "@/features/admin-billing/schemas/admin-billing.schema";
import type {
  AdminPaymentDetail,
  AdminRefund,
} from "@/features/admin-billing/types/admin-billing.types";
import { usePermissions } from "@/features/auth/hooks/use-permissions";
import { lotSourceLabels } from "@/features/credits/schemas/credits.schema";
import { formatCredits, formatDateTime, formatPaise } from "@/lib/utils/format";

export function RefundsList({ refunds }: { refunds: readonly AdminRefund[] }) {
  if (refunds.length === 0) {
    return <p className="text-sm text-muted-foreground">No refunds for this payment.</p>;
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead scope="col">Created</TableHead>
          <TableHead scope="col">Refund</TableHead>
          <TableHead scope="col">Status</TableHead>
          <TableHead scope="col">Amount</TableHead>
          <TableHead scope="col">Credits clawed back</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {refunds.map((refund) => (
          <TableRow key={refund.id}>
            <TableCell>{formatDateTime(refund.createdAt)}</TableCell>
            <TableCell>
              <Link
                href={adminBillingPaths.refund(refund.id)}
                className="font-mono text-xs hover:underline"
              >
                {refund.razorpayRefundId ?? refund.id.slice(0, 8)}
              </Link>
            </TableCell>
            <TableCell>
              <StatusBadge status={refund.status} />
            </TableCell>
            <TableCell className="font-mono">{formatPaise(refund.amountPaise)}</TableCell>
            <TableCell className="font-mono">{formatCredits(refund.creditsClawedBack)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function RefundAction({ payment }: { payment: AdminPaymentDetail }) {
  const { can } = usePermissions();
  if (!can("billing.refunds.create")) {
    return null;
  }
  if (payment.refundablePaise <= 0) {
    return (
      <p className="text-sm text-muted-foreground">
        {payment.status === "captured" || payment.status === "partially_refunded"
          ? "Nothing is left to refund on this payment."
          : "Only a captured payment can be refunded."}
      </p>
    );
  }
  return <RefundDialog payment={payment} />;
}

function PaymentSummary({ payment }: { payment: AdminPaymentDetail }) {
  return (
    <DetailSection title="Payment" actions={<RefundAction payment={payment} />}>
      <div className="flex flex-wrap gap-2">
        <StatusBadge status={payment.status} />
        {payment.flagged ? <Badge variant="destructive">Flagged for review</Badge> : null}
      </div>
      <DetailList
        items={[
          {
            label: "Razorpay payment",
            value: <span className="font-mono">{payment.razorpayPaymentId}</span>,
          },
          {
            label: "Amount (incl. GST)",
            value: <span className="font-mono">{formatPaise(payment.amountPaise)}</span>,
          },
          {
            label: "Refunded",
            value: <span className="font-mono">{formatPaise(payment.refundedPaise)}</span>,
          },
          {
            label: "Refund in progress",
            value: <span className="font-mono">{formatPaise(payment.pendingRefundPaise)}</span>,
          },
          {
            label: "Refundable now",
            value: <span className="font-mono">{formatPaise(payment.refundablePaise)}</span>,
          },
          { label: "Method", value: payment.method ?? "Unknown" },
          {
            label: "Razorpay fee",
            value: payment.feePaise === null ? "Not settled yet" : formatPaise(payment.feePaise),
          },
          {
            label: "Tax on fee",
            value: payment.taxPaise === null ? "Not settled yet" : formatPaise(payment.taxPaise),
          },
          { label: "Created", value: formatDateTime(payment.createdAt) },
          {
            label: "Captured",
            value:
              payment.capturedAt === null ? "Not captured" : formatDateTime(payment.capturedAt),
          },
          {
            label: "User",
            value: (
              <Link
                href={adminBillingPaths.user(payment.userId)}
                className="font-mono text-xs hover:underline"
              >
                {payment.userId}
              </Link>
            ),
          },
        ]}
      />
      {payment.errorCode ? (
        <p role="note" className="rounded-md border bg-elevated p-3 text-sm">
          Provider error <span className="font-mono">{payment.errorCode}</span>
          {payment.errorDescription ? `: ${payment.errorDescription}` : ""}
        </p>
      ) : null}
    </DetailSection>
  );
}

function PaymentOrder({ payment }: { payment: AdminPaymentDetail }) {
  const order = payment.order;
  return (
    <DetailSection title="Order">
      {order === null ? (
        <p className="text-sm text-muted-foreground">This payment is not linked to an order.</p>
      ) : (
        <>
          <div className="flex flex-wrap gap-2">
            <StatusBadge status={order.status} />
            {order.flagReason ? (
              <Badge variant="destructive">{flagReasonLabels[order.flagReason]}</Badge>
            ) : null}
          </div>
          <DetailList
            items={[
              {
                label: "Order",
                value: (
                  <Link
                    href={adminBillingPaths.order(order.id)}
                    className="font-mono text-xs hover:underline"
                  >
                    {order.receipt}
                  </Link>
                ),
              },
              {
                label: "Product",
                value: `${order.productName} (v${String(order.productVersion)})`,
              },
              {
                label: "Order amount (incl. GST)",
                value: <span className="font-mono">{formatPaise(order.amountPaise)}</span>,
              },
            ]}
          />
        </>
      )}
    </DetailSection>
  );
}

function PaymentSubscription({ payment }: { payment: AdminPaymentDetail }) {
  const subscription = payment.subscription;
  if (subscription === null) {
    return null;
  }
  return (
    <DetailSection title="Subscription">
      <DetailList
        items={[
          {
            label: "Plan",
            value: (
              <Link
                href={adminBillingPaths.subscription(subscription.id)}
                className="hover:underline"
              >
                {subscription.productName}
              </Link>
            ),
          },
          { label: "Status", value: <StatusBadge status={subscription.status} /> },
          {
            label: "Interval",
            value: subscription.interval ? intervalLabels[subscription.interval] : "-",
          },
        ]}
      />
      <p className="text-sm text-muted-foreground">
        Refunding this payment does not cancel the subscription, and cancelling the subscription
        does not refund this payment.
      </p>
    </DetailSection>
  );
}

function PaymentCredits({ payment }: { payment: AdminPaymentDetail }) {
  const lot = payment.lot;
  return (
    <DetailSection title="Credits granted">
      <DetailList
        items={[
          {
            label: "Credits granted",
            value: <span className="font-mono">{formatCredits(payment.creditsGranted)}</span>,
          },
          {
            label: "Clawed back if refunded in full",
            value: (
              <span className="font-mono">
                {formatCredits(payment.clawbackPreview.creditsToClawBack)}
              </span>
            ),
          },
        ]}
      />
      {lot === null ? (
        <p className="text-sm text-muted-foreground">This payment has no credit lot.</p>
      ) : (
        <DetailList
          items={[
            { label: "Lot source", value: lotSourceLabels[lot.source] },
            {
              label: "Lot amount",
              value: <span className="font-mono">{formatCredits(lot.amount)}</span>,
            },
            {
              label: "Lot remaining",
              value: <span className="font-mono">{formatCredits(lot.remaining)}</span>,
            },
            {
              label: "Lot status",
              value:
                lot.expiredAt !== null
                  ? `Expired on ${formatDateTime(lot.expiredAt)}`
                  : lot.expiresAt === null
                    ? "Never expires"
                    : `Expires on ${formatDateTime(lot.expiresAt)}`,
            },
          ]}
        />
      )}
    </DetailSection>
  );
}

export function PaymentDetail({ paymentId }: { paymentId: string }) {
  const payment = useAdminPayment(paymentId);
  if (payment.isPending) {
    return <Skeleton role="status" aria-label="Loading payment" className="h-96" />;
  }
  if (payment.isError) {
    return (
      <AdminBillingError
        error={payment.error}
        onRetry={() => {
          void payment.refetch();
        }}
      />
    );
  }
  return (
    <div className="space-y-6">
      <PaymentSummary payment={payment.data} />
      <PaymentOrder payment={payment.data} />
      <PaymentSubscription payment={payment.data} />
      <PaymentCredits payment={payment.data} />
      <DetailSection title="Refunds">
        <RefundsList refunds={payment.data.refunds} />
      </DetailSection>
    </div>
  );
}
