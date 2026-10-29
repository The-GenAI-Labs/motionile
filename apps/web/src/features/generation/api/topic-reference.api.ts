import { z } from "zod";

import { searchCatalog } from "@/features/catalog/api/catalog.api";

export interface ResolvedTopic {
  id: string;
  title: string | null;
  suggestedDurationSeconds: number | null;
}

const SLUG = /^[a-z0-9]+(-[a-z0-9]+)*$/;
const MAX_SLUG_CHARS = 120;
const MS_PER_SECOND = 1000;

export const resolveTopicReference = async (reference: string): Promise<ResolvedTopic | null> => {
  const id = z.uuid().safeParse(reference);
  if (id.success) {
    return { id: id.data, title: null, suggestedDurationSeconds: null };
  }
  if (reference.length > MAX_SLUG_CHARS || !SLUG.test(reference)) {
    return null;
  }
  const results = await searchCatalog(reference.replaceAll("-", " "));
  const match = results.items.find((topic) => topic.slug === reference);
  return match === undefined
    ? null
    : {
        id: match.id,
        title: match.title,
        suggestedDurationSeconds: Math.round(match.suggestedDurationMs / MS_PER_SECOND),
      };
};
