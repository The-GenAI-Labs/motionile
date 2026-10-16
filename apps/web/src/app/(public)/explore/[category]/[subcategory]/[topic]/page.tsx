import type { Metadata, Route } from "next";
import Link from "next/link";
import { notFound, permanentRedirect } from "next/navigation";

import { PageHeader } from "@/components/shared/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  CatalogFetchError,
  catalogPaths,
  catalogRedirect,
  catalogTopic,
} from "@/features/catalog/api/catalog.server.api";
import { CatalogBreadcrumbs } from "@/features/catalog/components/breadcrumbs";
import { TopicCard } from "@/features/catalog/components/topic-card";
import { buildMetadata } from "@/lib/seo/metadata";

export const revalidate = 3600;
export const dynamicParams = true;
interface Params {
  category: string;
  subcategory: string;
  topic: string;
}

const loadTopic = async ({ category, subcategory, topic }: Params) => {
  try {
    return await catalogTopic(category, subcategory, topic);
  } catch (error) {
    if (!(error instanceof CatalogFetchError) || error.status !== 404) throw error;
    try {
      permanentRedirect(
        (await catalogRedirect(`/explore/${category}/${subcategory}/${topic}`))
          .destination as Route,
      );
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
    return segments.length === 4
      ? [{ category: segments[1], subcategory: segments[2], topic: segments[3] }]
      : [];
  });
}

export async function generateMetadata({ params }: { params: Promise<Params> }): Promise<Metadata> {
  const values = await params;
  const data = await loadTopic(values);
  return buildMetadata({
    title: data.topic.seoTitle ?? data.topic.title,
    description:
      data.topic.seoDescription ??
      data.topic.summary ??
      `Generate an animated explainer about ${data.topic.title}.`,
    path: `/explore/${values.category}/${values.subcategory}/${values.topic}`,
    openGraphType: "article",
    images: [
      {
        url: `/explore/${values.category}/${values.subcategory}/${values.topic}/opengraph-image`,
        width: 1200,
        height: 630,
        alt: `${data.topic.title} on Motionile`,
      },
    ],
  });
}

export default async function TopicPage({ params }: { params: Promise<Params> }) {
  const values = await params;
  const data = await loadTopic(values);
  return (
    <div className="mx-auto w-full max-w-5xl space-y-10 px-4 py-12 sm:px-6 lg:px-8">
      <CatalogBreadcrumbs
        items={[
          { name: "Explore", path: "/explore" },
          { name: data.category.name, path: `/explore/${values.category}` },
          {
            name: data.subcategory.name,
            path: `/explore/${values.category}/${values.subcategory}`,
          },
          {
            name: data.topic.title,
            path: `/explore/${values.category}/${values.subcategory}/${values.topic}`,
          },
        ]}
      />
      <article className="space-y-8">
        <PageHeader
          title={data.topic.title}
          description={data.topic.summary}
          eyebrow={`${data.category.name} · ${data.subcategory.name}`}
          actions={
            <Button asChild size="lg">
              <Link href={`/create?topic=${data.topic.id}` as Route}>Generate this video</Link>
            </Button>
          }
        />
        <div className="flex flex-wrap gap-3">
          <Badge variant="outline" className="capitalize">
            {data.topic.difficulty}
          </Badge>
          <Badge variant="outline">
            {Math.round(data.topic.suggestedDurationMs / 1000)} seconds
          </Badge>
          {data.topic.skillHints.map((skill) => (
            <Badge key={skill} variant="secondary">
              {skill}
            </Badge>
          ))}
        </div>
      </article>
      {data.relatedTopics.length > 0 ? (
        <section aria-labelledby="related-topics" className="space-y-4">
          <h2 id="related-topics" className="text-2xl font-semibold">
            Related topics
          </h2>
          <div className="grid gap-4 md:grid-cols-2">
            {data.relatedTopics.map((topic) => (
              <TopicCard
                key={topic.id}
                topic={topic}
                href={`/explore/${values.category}/${values.subcategory}/${topic.slug}`}
              />
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}
