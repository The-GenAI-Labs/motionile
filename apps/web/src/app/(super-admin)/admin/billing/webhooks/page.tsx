import { PageHeader } from "@/components/shared/page-header";
import { WebhooksTable } from "@/features/admin-billing/components/webhooks-table";
import { requirePermissions } from "@/lib/auth/require-permissions";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata = buildMetadata({
  title: "Billing webhooks",
  description: "Inspect and reprocess Razorpay webhook events received by Motionile.",
  path: "/admin/billing/webhooks",
  noIndex: true,
});

export default async function BillingWebhooksPage() {
  await requirePermissions(["billing.webhooks.manage"]);
  return (
    <div className="space-y-8">
      <PageHeader
        title="Webhooks"
        description="Razorpay events received by Motionile and how they were processed."
      />
      <WebhooksTable />
    </div>
  );
}
