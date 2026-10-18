import { PageHeader } from "@/components/shared/page-header";
import { OrdersTable } from "@/features/admin-billing/components/orders-table";
import { requirePermissions } from "@/lib/auth/require-permissions";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata = buildMetadata({
  title: "Billing orders",
  description: "Review Motionile orders and the ones flagged for attention.",
  path: "/admin/billing/orders",
  noIndex: true,
});

export default async function BillingOrdersPage() {
  await requirePermissions(["billing.read"]);
  return (
    <div className="space-y-8">
      <PageHeader title="Orders" description="Orders, including the ones flagged for review." />
      <OrdersTable />
    </div>
  );
}
