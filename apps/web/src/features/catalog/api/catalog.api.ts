import * as contract from "@motionile/api-contract";

import { apiClient } from "@/lib/api/client";

export const searchCatalog = async (query: string, cursor?: string) => {
  const response = await apiClient.get<unknown>("/v1/catalog/search", {
    params: { q: query, cursor },
  });
  return contract.zTopicSearchResponse.parse(response.data);
};

export const loadSubcategoryPage = async (
  category: string,
  subcategory: string,
  cursor?: string,
) => {
  const response = await apiClient.get<unknown>(
    `/v1/catalog/categories/${encodeURIComponent(category)}/${encodeURIComponent(subcategory)}`,
    { params: { cursor } },
  );
  return contract.zSubcategoryDetailResponse.parse(response.data);
};
