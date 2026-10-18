import { PageHeader } from "@/components/shared/page-header";
import { BillingOverview } from "@/features/admin-billing/components/billing-overview";
import { requirePermissions } from "@/lib/auth/require-permissions";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata = buildMetadata({
  title: "Billing overview",
  description:
    "Revenue, subscriptions, credits and items that need attention in the Motionile billing console.",
  path: "/admin/billing",
  noIndex: true,
});

export default async function BillingOverviewPage() {
  await requirePermissions(["billing.read"]);
  return (
    <div className="space-y-8">
      <PageHeader
        title="Billing"
        description="Revenue, subscriptions, credits and the items that need your attention."
      />
      <BillingOverview />
    </div>
  );
}
