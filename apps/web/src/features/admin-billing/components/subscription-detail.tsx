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
import { CancelSubscriptionDialog } from "@/features/admin-billing/components/cancel-subscription-dialog";
import { DetailList, DetailSection } from "@/features/admin-billing/components/detail-section";
import { StatusBadge } from "@/features/admin-billing/components/status-badge";
import { useAdminSubscription } from "@/features/admin-billing/hooks/use-admin-subscriptions";
import { adminBillingPaths } from "@/features/admin-billing/paths";
import { intervalLabels } from "@/features/admin-billing/schemas/admin-billing.schema";
import type { AdminSubscriptionDetail } from "@/features/admin-billing/types/admin-billing.types";
import { usePermissions } from "@/features/auth/hooks/use-permissions";
import { formatCredits, formatDate, formatDateTime, formatPaise } from "@/lib/utils/format";

const ENDED_STATUSES = new Set(["cancelled", "completed", "expired"]);

function CancelAction({ subscription }: { subscription: AdminSubscriptionDetail }) {
  const { can } = usePermissions();
  if (!can("billing.refunds.create")) {
    return null;
  }
  if (ENDED_STATUSES.has(subscription.status)) {
    return <p className="text-sm text-muted-foreground">This subscription has already ended.</p>;
  }
  if (subscription.cancelAtPeriodEnd) {
    return (
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-sm text-muted-foreground">
          This subscription is already set to end at the end of its period.
        </p>
        <CancelSubscriptionDialog subscription={subscription} />
      </div>
    );
  }
  return <CancelSubscriptionDialog subscription={subscription} />;
}

function SubscriptionSummary({ subscription }: { subscription: AdminSubscriptionDetail }) {
  const { product, pendingProduct } = subscription;
  return (
    <DetailSection title="Subscription" actions={<CancelAction subscription={subscription} />}>
      <div className="flex flex-wrap gap-2">
        <StatusBadge status={subscription.status} />
        {subscription.cancelAtPeriodEnd ? (
          <Badge variant="outline">Ends at period end</Badge>
        ) : null}
      </div>
      <DetailList
        items={[
          {
            label: "Plan",
            value: (
              <Link href={adminBillingPaths.product(product.id)} className="hover:underline">
                {product.name}
              </Link>
            ),
          },
          {
            label: "Price (incl. GST)",
            value: (
              <span className="font-mono">
                {formatPaise(product.pricePaise)}
                {product.interval ? ` ${intervalLabels[product.interval].toLowerCase()}` : ""}
              </span>
            ),
          },
          {
            label: "Credits each period",
            value: <span className="font-mono">{formatCredits(product.creditsGranted)}</span>,
          },
          {
            label: "Razorpay subscription",
            value: (
              <span className="font-mono">
                {subscription.razorpaySubscriptionId ?? "Not created"}
              </span>
            ),
          },
          {
            label: "Charges",
            value: (
              <span className="font-mono">
                {subscription.paidCount} of {subscription.totalCount}
              </span>
            ),
          },
          {
            label: "Current period",
            value:
              subscription.currentPeriodStart && subscription.currentPeriodEnd
                ? `${formatDate(subscription.currentPeriodStart)} to ${formatDate(subscription.currentPeriodEnd)}`
                : "Not started",
          },
          {
            label: "Next charge",
            value: subscription.nextChargeAt ? formatDate(subscription.nextChargeAt) : "None",
          },
          { label: "Created", value: formatDateTime(subscription.createdAt) },
          ...(subscription.cancelledAt
            ? [{ label: "Cancelled", value: formatDateTime(subscription.cancelledAt) }]
            : []),
          ...(subscription.endedAt
            ? [{ label: "Ended", value: formatDateTime(subscription.endedAt) }]
            : []),
          ...(pendingProduct
            ? [{ label: "Changes to next period", value: pendingProduct.name }]
            : []),
          {
            label: "User",
            value: (
              <Link
                href={adminBillingPaths.user(subscription.userId)}
                className="font-mono text-xs hover:underline"
              >
                {subscription.userId}
              </Link>
            ),
          },
        ]}
      />
      <p className="text-sm text-muted-foreground">
        Cancelling a subscription never refunds a payment, and refunding a payment never cancels the
        subscription.
      </p>
    </DetailSection>
  );
}

function SubscriptionPayments({ subscription }: { subscription: AdminSubscriptionDetail }) {
  if (subscription.payments.length === 0) {
    return <p className="text-sm text-muted-foreground">No payments yet.</p>;
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead scope="col">Date</TableHead>
          <TableHead scope="col">Payment</TableHead>
          <TableHead scope="col">Status</TableHead>
          <TableHead scope="col">Amount (incl. GST)</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {subscription.payments.map((payment) => (
          <TableRow key={payment.id}>
            <TableCell>{formatDateTime(payment.createdAt)}</TableCell>
            <TableCell>
              <Link
                href={adminBillingPaths.payment(payment.id)}
                className="font-mono text-xs hover:underline"
              >
                {payment.razorpayPaymentId}
              </Link>
            </TableCell>
            <TableCell>
              <StatusBadge status={payment.status} />
            </TableCell>
            <TableCell className="font-mono">{formatPaise(payment.amountPaise)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

export function SubscriptionDetail({ subscriptionId }: { subscriptionId: string }) {
  const subscription = useAdminSubscription(subscriptionId);
  if (subscription.isPending) {
    return <Skeleton role="status" aria-label="Loading subscription" className="h-96" />;
  }
  if (subscription.isError) {
    return (
      <AdminBillingError
        error={subscription.error}
        onRetry={() => {
          void subscription.refetch();
        }}
      />
    );
  }
  return (
    <div className="space-y-6">
      <SubscriptionSummary subscription={subscription.data} />
      <DetailSection title="Payments">
        <SubscriptionPayments subscription={subscription.data} />
      </DetailSection>
    </div>
  );
}
