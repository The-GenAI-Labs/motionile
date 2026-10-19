import { PageHeader } from "@/components/shared/page-header";
import { PaymentDetail } from "@/features/admin-billing/components/payment-detail";
import { requirePermissions } from "@/lib/auth/require-permissions";
import { buildMetadata } from "@/lib/seo/metadata";
import { uuidParam } from "@/lib/utils/route-params";

export const metadata = buildMetadata({
  title: "Payment detail",
  description: "Review a Motionile payment, its credits and refunds.",
  path: "/admin/billing/payments",
  noIndex: true,
});

export default async function BillingPaymentPage({
  params,
}: {
  params: Promise<{ paymentId: string }>;
}) {
  await requirePermissions(["billing.read"]);
  const { paymentId } = await params;
  return (
    <div className="space-y-8">
      <PageHeader
        title="Payment"
        description="The order, credits and refunds behind this payment."
      />
      <PaymentDetail paymentId={uuidParam(paymentId)} />
    </div>
  );
}
