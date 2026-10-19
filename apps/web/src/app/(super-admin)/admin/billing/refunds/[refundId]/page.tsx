import { PageHeader } from "@/components/shared/page-header";
import { RefundDetail } from "@/features/admin-billing/components/refund-detail";
import { requirePermissions } from "@/lib/auth/require-permissions";
import { buildMetadata } from "@/lib/seo/metadata";
import { uuidParam } from "@/lib/utils/route-params";

export const metadata = buildMetadata({
  title: "Refund detail",
  description: "Review a Motionile refund.",
  path: "/admin/billing/refunds",
  noIndex: true,
});

export default async function BillingRefundPage({
  params,
}: {
  params: Promise<{ refundId: string }>;
}) {
  await requirePermissions(["billing.read"]);
  const { refundId } = await params;
  return (
    <div className="space-y-8">
      <PageHeader title="Refund" description="Amounts, status and clawback for this refund." />
      <RefundDetail refundId={uuidParam(refundId)} />
    </div>
  );
}
