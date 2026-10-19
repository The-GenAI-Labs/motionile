import { PageHeader } from "@/components/shared/page-header";
import { RunsTable } from "@/features/admin-billing/components/runs-table";
import { requirePermissions } from "@/lib/auth/require-permissions";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata = buildMetadata({
  title: "Billing reconciliation",
  description: "Review Motionile payment reconciliation runs and download their reports.",
  path: "/admin/billing/reconciliation",
  noIndex: true,
});

export default async function BillingReconciliationPage() {
  await requirePermissions(["billing.read"]);
  return (
    <div className="space-y-8">
      <PageHeader
        title="Reconciliation"
        description="Scheduled checks that compare Razorpay with our records."
      />
      <RunsTable />
    </div>
  );
}
