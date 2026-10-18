import { PageHeader } from "@/components/shared/page-header";
import { BillingOverview } from "@/features/billing/components/billing-overview";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata = buildMetadata({
  title: "Billing",
  description: "See your Motionile credits, current plan and recent billing activity.",
  path: "/billing",
  noIndex: true,
});

export default function BillingPage() {
  return (
    <div className="space-y-8">
      <PageHeader
        title="Billing"
        description="Your credits, your plan and a quick way to top up."
      />
      <BillingOverview />
    </div>
  );
}
