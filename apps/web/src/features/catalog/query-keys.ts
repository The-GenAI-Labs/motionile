export const catalogKeys = {
  all: ["catalog"] as const,
  search: (query: string) => [...catalogKeys.all, "search", query] as const,
  subcategory: (category: string, subcategory: string) =>
    [...catalogKeys.all, "subcategory", category, subcategory] as const,
};
