import { PageHeader } from "@/components/shared/page-header";
import { PaymentsTable } from "@/features/admin-billing/components/payments-table";
import { requirePermissions } from "@/lib/auth/require-permissions";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata = buildMetadata({
  title: "Billing payments",
  description: "Review Motionile payments and refund them.",
  path: "/admin/billing/payments",
  noIndex: true,
});

export default async function BillingPaymentsPage() {
  await requirePermissions(["billing.read"]);
  return (
    <div className="space-y-8">
      <PageHeader title="Payments" description="Every payment captured through Razorpay." />
      <PaymentsTable />
    </div>
  );
}
