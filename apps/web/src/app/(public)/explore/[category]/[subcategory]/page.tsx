import type { Metadata, Route } from "next";
import { notFound, permanentRedirect } from "next/navigation";

import { PageHeader } from "@/components/shared/page-header";
import {
  CatalogFetchError,
  catalogRedirect,
  catalogStaticPaths,
  catalogSubcategory,
} from "@/features/catalog/api/catalog.server.api";
import { CatalogBreadcrumbs } from "@/features/catalog/components/breadcrumbs";
import { TopicList } from "@/features/catalog/components/topic-list";
import { buildMetadata } from "@/lib/seo/metadata";

export const revalidate = 3600;
export const dynamicParams = true;
interface Params {
  category: string;
  subcategory: string;
}

const loadSubcategory = async ({ category, subcategory }: Params) => {
  try {
    return await catalogSubcategory(category, subcategory);
  } catch (error) {
    if (!(error instanceof CatalogFetchError) || error.status !== 404) throw error;
    try {
      permanentRedirect(
        (await catalogRedirect(`/explore/${category}/${subcategory}`)).destination as Route,
      );
    } catch (redirectError) {
      if (redirectError instanceof CatalogFetchError && redirectError.status === 404) notFound();
      throw redirectError;
    }
  }
};

export async function generateStaticParams() {
  const paths = await catalogStaticPaths();
  return paths.flatMap(({ path }) => {
    const segments = path.split("/").filter(Boolean);
    return segments.length === 3 ? [{ category: segments[1], subcategory: segments[2] }] : [];
  });
}

export async function generateMetadata({ params }: { params: Promise<Params> }): Promise<Metadata> {
  const values = await params;
  const data = await loadSubcategory(values);
  return buildMetadata({
    title: data.subcategory.seoTitle ?? data.subcategory.name,
    description:
      data.subcategory.seoDescription ??
      data.subcategory.description ??
      `Explore ${data.subcategory.name} topics on Motionile.`,
    path: `/explore/${values.category}/${values.subcategory}`,
  });
}

export default async function SubcategoryPage({ params }: { params: Promise<Params> }) {
  const values = await params;
  const data = await loadSubcategory(values);
  return (
    <div className="mx-auto w-full max-w-7xl space-y-10 px-4 py-12 sm:px-6 lg:px-8">
      <CatalogBreadcrumbs
        items={[
          { name: "Explore", path: "/explore" },
          { name: data.category.name, path: `/explore/${values.category}` },
          {
            name: data.subcategory.name,
            path: `/explore/${values.category}/${values.subcategory}`,
          },
        ]}
      />
      <PageHeader title={data.subcategory.name} description={data.subcategory.description} />
      <TopicList
        category={values.category}
        subcategory={values.subcategory}
        initialTopics={data.topics.items}
        initialCursor={data.topics.nextCursor ?? null}
      />
    </div>
  );
}
