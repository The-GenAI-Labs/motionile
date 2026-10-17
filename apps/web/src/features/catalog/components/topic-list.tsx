"use client";

import type { zCatalogTopicResponse } from "@motionile/api-contract";
import { useState } from "react";
import type { z } from "zod";

import { CursorPagination } from "@/components/shared/cursor-pagination";
import { loadSubcategoryPage } from "@/features/catalog/api/catalog.api";
import { TopicCard } from "@/features/catalog/components/topic-card";

type Topic = z.infer<typeof zCatalogTopicResponse>;

interface TopicListProps {
  category: string;
  subcategory: string;
  initialTopics: Topic[];
  initialCursor: string | null;
}

export function TopicList({ category, subcategory, initialTopics, initialCursor }: TopicListProps) {
  const [topics, setTopics] = useState(initialTopics);
  const [cursor, setCursor] = useState<string | null>(initialCursor);
  const [loading, setLoading] = useState(false);
  const loadMore = async () => {
    if (cursor === null) {
      return;
    }
    setLoading(true);
    try {
      const page = await loadSubcategoryPage(category, subcategory, cursor);
      setTopics((current) => [
        ...current,
        ...page.topics.items.filter((topic) => !current.some((item) => item.id === topic.id)),
      ]);
      setCursor(page.topics.nextCursor ?? null);
    } finally {
      setLoading(false);
    }
  };
  return (
    <div>
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {topics.map((topic) => (
          <TopicCard
            key={topic.id}
            topic={topic}
            href={`/explore/${category}/${subcategory}/${topic.slug}`}
          />
        ))}
      </div>
      <CursorPagination
        hasNextPage={cursor !== null}
        isFetchingNextPage={loading}
        fetchNextPage={loadMore}
        endLabel="All topics are shown."
      />
    </div>
  );
}
