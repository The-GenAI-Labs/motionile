import { catalogTopic } from "@/features/catalog/api/catalog.server.api";
import { catalogOpenGraph } from "@/features/catalog/components/catalog-opengraph";
import { OPEN_GRAPH_IMAGE_SIZE } from "@/lib/seo/metadata";

export const size = OPEN_GRAPH_IMAGE_SIZE;
export const contentType = "image/png";
export const alt = "A Motionile explainer topic";

export default async function TopicOpenGraph({
  params,
}: {
  params: Promise<{ category: string; subcategory: string; topic: string }>;
}) {
  const values = await params;
  const data = await catalogTopic(values.category, values.subcategory, values.topic);
  return catalogOpenGraph(data.topic.title, `${data.category.name} · ${data.subcategory.name}`);
}
