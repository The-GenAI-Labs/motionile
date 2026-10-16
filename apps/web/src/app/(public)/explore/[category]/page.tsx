import type { Metadata, Route } from "next";
import Link from "next/link";
import { notFound, permanentRedirect } from "next/navigation";

import { PageHeader } from "@/components/shared/page-header";
import {
  catalogCategory,
  CatalogFetchError,
  catalogPaths,
  catalogRedirect,
} from "@/features/catalog/api/catalog.server.api";
import { CatalogBreadcrumbs } from "@/features/catalog/components/breadcrumbs";
import { buildMetadata } from "@/lib/seo/metadata";

export const revalidate = 3600;
export const dynamicParams = true;

const loadCategory = async (category: string) => {
  try {
    return await catalogCategory(category);
  } catch (error) {
    if (!(error instanceof CatalogFetchError) || error.status !== 404) throw error;
    try {
      permanentRedirect((await catalogRedirect(`/explore/${category}`)).destination as Route);
    } catch (redirectError) {
      if (redirectError instanceof CatalogFetchError && redirectError.status === 404) notFound();
      throw redirectError;
    }
  }
};

export async function generateStaticParams() {
  const paths = await catalogPaths();
  return paths.items.flatMap(({ path }) => {
    const segments = path.split("/").filter(Boolean);
    return segments.length === 2 ? [{ category: segments[1] }] : [];
  });
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ category: string }>;
}): Promise<Metadata> {
  const { category } = await params;
  const data = await loadCategory(category);
  return buildMetadata({
    title: data.category.seoTitle ?? data.category.name,
    description:
      data.category.seoDescription ??
      data.category.description ??
      `Explore ${data.category.name} topics on Motionile.`,
    path: `/explore/${category}`,
    images: [
      {
        url: `/explore/${category}/opengraph-image`,
        width: 1200,
        height: 630,
        alt: `${data.category.name} topics on Motionile`,
      },
    ],
  });
}

export default async function CategoryPage({ params }: { params: Promise<{ category: string }> }) {
  const { category } = await params;
  const data = await loadCategory(category);
  return (
    <div className="mx-auto w-full max-w-7xl space-y-10 px-4 py-12 sm:px-6 lg:px-8">
      <CatalogBreadcrumbs
        items={[
          { name: "Explore", path: "/explore" },
          { name: data.category.name, path: `/explore/${category}` },
        ]}
      />
      <PageHeader title={data.category.name} description={data.category.description} />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {data.subcategories.map((subcategory) => (
          <Link
            key={subcategory.id}
            href={`/explore/${category}/${subcategory.slug}` as Route}
            className="rounded-xl border bg-surface p-6 hover:bg-elevated focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none"
          >
            <h2 className="text-lg font-semibold">{subcategory.name}</h2>
            {subcategory.description ? (
              <p className="mt-2 text-sm text-subtle-foreground">{subcategory.description}</p>
            ) : null}
          </Link>
        ))}
      </div>
    </div>
  );
}
