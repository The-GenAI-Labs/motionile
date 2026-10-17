import { catalogCategory } from "@/features/catalog/api/catalog.server.api";
import { catalogOpenGraph } from "@/features/catalog/components/catalog-opengraph";
import { OPEN_GRAPH_IMAGE_SIZE } from "@/lib/seo/metadata";

export const size = OPEN_GRAPH_IMAGE_SIZE;
export const contentType = "image/png";
export const alt = "Explore topics on Motionile";

export default async function CategoryOpenGraph({
  params,
}: {
  params: Promise<{ category: string }>;
}) {
  const { category } = await params;
  const data = await catalogCategory(category);
  return catalogOpenGraph(data.category.name, "Explore category");
}
