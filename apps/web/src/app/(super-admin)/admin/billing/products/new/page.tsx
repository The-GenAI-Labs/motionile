import { PageHeader } from "@/components/shared/page-header";
import { NewProduct } from "@/features/admin-billing/components/new-product";
import { requirePermissions } from "@/lib/auth/require-permissions";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata = buildMetadata({
  title: "New billing product",
  description: "Create a Motionile credit pack or subscription plan.",
  path: "/admin/billing/products/new",
  noIndex: true,
});

export default async function NewBillingProductPage() {
  await requirePermissions(["billing.products.manage"]);
  return (
    <div className="space-y-8">
      <PageHeader
        title="New product"
        description="Create a credit pack or a subscription plan. Prices include GST."
      />
      <NewProduct />
    </div>
  );
}
