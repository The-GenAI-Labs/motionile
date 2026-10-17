import "server-only";

import * as contract from "@motionile/api-contract";
import type { z } from "zod";

import { serverEnv } from "@/config/server-env";

export const CATALOG_REVALIDATE_SECONDS = 3600;

export class CatalogFetchError extends Error {
  constructor(readonly status: number) {
    super(`Catalog request failed with status ${status}`);
  }
}

const catalogFetch = async <Schema extends z.ZodType>(
  path: string,
  schema: Schema,
  tags: string[],
): Promise<z.output<Schema>> => {
  const response = await fetch(new URL(path, `${serverEnv.apiBaseUrl}/`), {
    headers: { accept: "application/json" },
    next: { revalidate: CATALOG_REVALIDATE_SECONDS, tags },
  });
  if (!response.ok) {
    throw new CatalogFetchError(response.status);
  }
  return schema.parse(await response.json());
};

export const catalogTree = () =>
  catalogFetch("v1/catalog/tree", contract.zCatalogTreeResponse, ["catalog", "catalog:tree"]);
export const catalogCategory = (category: string) =>
  catalogFetch(
    `v1/catalog/categories/${encodeURIComponent(category)}`,
    contract.zCategoryDetailResponse,
    ["catalog", `catalog:category:${category}`],
  );
export const catalogSubcategory = (category: string, subcategory: string, cursor?: string) => {
  const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : "";
  return catalogFetch(
    `v1/catalog/categories/${encodeURIComponent(category)}/${encodeURIComponent(subcategory)}${query}`,
    contract.zSubcategoryDetailResponse,
    ["catalog", `catalog:category:${category}`, `catalog:subcategory:${category}/${subcategory}`],
  );
};
export const catalogTopic = (category: string, subcategory: string, topic: string) =>
  catalogFetch(
    `v1/catalog/topics/${encodeURIComponent(category)}/${encodeURIComponent(subcategory)}/${encodeURIComponent(topic)}`,
    contract.zTopicDetailResponse,
    ["catalog", `catalog:topic:${category}/${subcategory}/${topic}`],
  );
export const catalogPaths = () =>
  catalogFetch("v1/catalog/paths", contract.zCatalogPathsResponse, ["catalog", "catalog:paths"]);
export const catalogStaticPaths = async () => {
  try {
    return (await catalogPaths()).items;
  } catch (error) {
    if (error instanceof TypeError) return [];
    throw error;
  }
};
export const catalogRedirect = (path: string) =>
  catalogFetch(
    `v1/catalog/redirects?path=${encodeURIComponent(path)}`,
    contract.zCatalogRedirectResponse,
    ["catalog", `catalog:redirect:${path}`],
  );
