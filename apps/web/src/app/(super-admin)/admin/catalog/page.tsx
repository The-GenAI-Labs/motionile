import { PageHeader } from "@/components/shared/page-header";
import { CatalogManager } from "@/features/admin/components/catalog-manager";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata = buildMetadata({
  title: "Catalog",
  description: "Manage the Motionile topic catalog.",
  path: "/admin/catalog",
  noIndex: true,
});

export default function AdminCatalogPage() {
  return (
    <div className="space-y-8">
      <PageHeader
        title="Catalog"
        description="Manage categories, subcategories, topics, visibility, and search metadata."
      />
      <CatalogManager />
    </div>
  );
}
