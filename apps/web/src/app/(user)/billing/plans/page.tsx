import { PageHeader } from "@/components/shared/page-header";
import { PlansManager } from "@/features/billing/components/plans-manager";
import { parseProductCode } from "@/features/billing/schemas/billing.schema";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata = buildMetadata({
  title: "Plans",
  description: "Subscribe to a Motionile plan, change plans or cancel at the end of the period.",
  path: "/billing/plans",
  noIndex: true,
});

interface PlansPageProps {
  searchParams: Promise<{ plan?: string | string[] }>;
}

export default async function PlansPage({ searchParams }: PlansPageProps) {
  const { plan } = await searchParams;
  return (
    <div className="space-y-8">
      <PageHeader
        title="Plans"
        description="Subscription credits renew every billing period. Change plans from the next cycle or cancel at the end of the period."
      />
      <PlansManager requestedPlan={parseProductCode(plan)} />
    </div>
  );
}
