import type { MetadataRoute } from "next";

import { publicPages } from "@/config/navigation";
import { catalogPaths } from "@/features/catalog/api/catalog.server.api";
import { absoluteUrl } from "@/lib/seo/metadata";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const catalog = await catalogPaths();
  return [
    ...publicPages.map((page) => ({
      url: absoluteUrl(page.path),
      changeFrequency: page.changeFrequency,
      priority: page.priority,
    })),
    ...catalog.items.map((item) => ({
      url: absoluteUrl(item.path),
      lastModified: item.lastModified,
      changeFrequency: "weekly" as const,
      priority: item.path === "/explore" ? 0.9 : 0.7,
    })),
  ];
}
