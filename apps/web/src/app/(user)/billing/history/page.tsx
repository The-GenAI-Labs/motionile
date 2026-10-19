import { PageHeader } from "@/components/shared/page-header";
import { BillingHistory } from "@/features/billing/components/billing-history";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata = buildMetadata({
  title: "Billing history",
  description: "Review your Motionile payments, credit ledger and credit usage.",
  path: "/billing/history",
  noIndex: true,
});

export default function BillingHistoryPage() {
  return (
    <div className="space-y-8">
      <PageHeader
        title="History"
        description="Your payments and orders, every change to your credits and where they were used."
      />
      <BillingHistory />
    </div>
  );
}
