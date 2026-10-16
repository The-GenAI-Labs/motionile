import Link from "next/link";

import { PageHeader } from "@/components/shared/page-header";
import { catalogTree } from "@/features/catalog/api/catalog.server.api";
import { CatalogBreadcrumbs } from "@/features/catalog/components/breadcrumbs";
import { ExploreSearch } from "@/features/catalog/components/explore-search";
import { buildMetadata } from "@/lib/seo/metadata";

export const revalidate = 3600;
export const metadata = buildMetadata({
  title: "Explore",
  description: "Browse explainer video topics across education, technology and more.",
  path: "/explore",
});

export default async function ExplorePage() {
  const tree = await catalogTree();
  return (
    <div className="mx-auto w-full max-w-7xl space-y-12 px-4 py-12 sm:px-6 lg:px-8">
      <CatalogBreadcrumbs items={[{ name: "Explore", path: "/explore" }]} />
      <PageHeader
        title="Explore topics"
        description="Choose a subject and turn a focused topic into a clear animated explainer."
      />
      <section aria-labelledby="categories-title">
        <h2 id="categories-title" className="sr-only">
          Categories
        </h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {tree.categories.map((category) => (
            <Link
              key={category.id}
              href={`/explore/${category.slug}`}
              className="rounded-xl border bg-surface p-6 transition-colors hover:bg-elevated focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none"
            >
              <h3 className="text-xl font-semibold">{category.name}</h3>
              {category.description ? (
                <p className="mt-2 text-sm text-subtle-foreground">{category.description}</p>
              ) : null}
              <p className="mt-4 font-mono text-xs text-muted-foreground">
                {category.children.length} subcategories
              </p>
            </Link>
          ))}
        </div>
      </section>
      <ExploreSearch />
    </div>
  );
}
