import { PageHeader } from "@/components/shared/page-header";
import { SubscriptionDetail } from "@/features/admin-billing/components/subscription-detail";
import { requirePermissions } from "@/lib/auth/require-permissions";
import { buildMetadata } from "@/lib/seo/metadata";
import { uuidParam } from "@/lib/utils/route-params";

export const metadata = buildMetadata({
  title: "Subscription detail",
  description: "Review a Motionile subscription and cancel it.",
  path: "/admin/billing/subscriptions",
  noIndex: true,
});

export default async function BillingSubscriptionPage({
  params,
}: {
  params: Promise<{ subscriptionId: string }>;
}) {
  await requirePermissions(["billing.read"]);
  const { subscriptionId } = await params;
  return (
    <div className="space-y-8">
      <PageHeader
        title="Subscription"
        description="Plan, status and payments of this subscription."
      />
      <SubscriptionDetail subscriptionId={uuidParam(subscriptionId)} />
    </div>
  );
}
