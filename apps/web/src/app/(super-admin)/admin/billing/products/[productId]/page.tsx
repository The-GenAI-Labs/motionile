import { PageHeader } from "@/components/shared/page-header";
import { ProductDetail } from "@/features/admin-billing/components/product-detail";
import { requirePermissions } from "@/lib/auth/require-permissions";
import { buildMetadata } from "@/lib/seo/metadata";
import { uuidParam } from "@/lib/utils/route-params";

export const metadata = buildMetadata({
  title: "Product detail",
  description: "Review, edit and version a Motionile billing product.",
  path: "/admin/billing/products",
  noIndex: true,
});

export default async function BillingProductPage({
  params,
}: {
  params: Promise<{ productId: string }>;
}) {
  await requirePermissions(["billing.read"]);
  const { productId } = await params;
  return (
    <div className="space-y-8">
      <PageHeader title="Product" description="Details, state and versions of this product." />
      <ProductDetail productId={uuidParam(productId)} />
    </div>
  );
}
