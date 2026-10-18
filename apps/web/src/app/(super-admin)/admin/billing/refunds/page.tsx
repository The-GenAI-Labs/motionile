import { PageHeader } from "@/components/shared/page-header";
import { RefundsTable } from "@/features/admin-billing/components/refunds-table";
import { requirePermissions } from "@/lib/auth/require-permissions";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata = buildMetadata({
  title: "Billing refunds",
  description: "Review refunds issued for Motionile payments.",
  path: "/admin/billing/refunds",
  noIndex: true,
});

export default async function BillingRefundsPage() {
  await requirePermissions(["billing.read"]);
  return (
    <div className="space-y-8">
      <PageHeader
        title="Refunds"
        description="Refunds issued for payments and the credits they clawed back."
      />
      <RefundsTable />
    </div>
  );
}
