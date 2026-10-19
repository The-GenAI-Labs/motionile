import { PageHeader } from "@/components/shared/page-header";
import { SubscriptionsTable } from "@/features/admin-billing/components/subscriptions-table";
import { requirePermissions } from "@/lib/auth/require-permissions";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata = buildMetadata({
  title: "Billing subscriptions",
  description: "Review Motionile subscriptions and cancel them.",
  path: "/admin/billing/subscriptions",
  noIndex: true,
});

export default async function BillingSubscriptionsPage() {
  await requirePermissions(["billing.read"]);
  return (
    <div className="space-y-8">
      <PageHeader title="Subscriptions" description="Subscriptions and their billing status." />
      <SubscriptionsTable />
    </div>
  );
}
