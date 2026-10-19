import { PageHeader } from "@/components/shared/page-header";
import { OrderDetail } from "@/features/admin-billing/components/order-detail";
import { requirePermissions } from "@/lib/auth/require-permissions";
import { buildMetadata } from "@/lib/seo/metadata";
import { uuidParam } from "@/lib/utils/route-params";

export const metadata = buildMetadata({
  title: "Order detail",
  description: "Review a Motionile order and any reason it was flagged.",
  path: "/admin/billing/orders",
  noIndex: true,
});

export default async function BillingOrderPage({
  params,
}: {
  params: Promise<{ orderId: string }>;
}) {
  await requirePermissions(["billing.read"]);
  const { orderId } = await params;
  return (
    <div className="space-y-8">
      <PageHeader title="Order" description="The order and its payments." />
      <OrderDetail orderId={uuidParam(orderId)} />
    </div>
  );
}
