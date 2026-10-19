import { PageHeader } from "@/components/shared/page-header";
import { ProductsTable } from "@/features/admin-billing/components/products-table";
import { requirePermissions } from "@/lib/auth/require-permissions";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata = buildMetadata({
  title: "Billing products",
  description: "Review and manage Motionile credit packs and subscription plans.",
  path: "/admin/billing/products",
  noIndex: true,
});

export default async function BillingProductsPage() {
  await requirePermissions(["billing.read"]);
  return (
    <div className="space-y-8">
      <PageHeader
        title="Products"
        description="Credit packs and subscription plans. Prices include GST."
      />
      <ProductsTable />
    </div>
  );
}
