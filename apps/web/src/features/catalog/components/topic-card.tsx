import type { zCatalogTopicResponse } from "@motionile/api-contract";
import type { Route } from "next";
import Link from "next/link";
import type { z } from "zod";

import { Badge } from "@/components/ui/badge";

export type CatalogTopic = z.infer<typeof zCatalogTopicResponse>;

export function TopicCard({ topic, href }: { topic: CatalogTopic; href: string }) {
  return (
    <article className="flex h-full flex-col rounded-xl border bg-surface p-5 transition-colors hover:bg-elevated">
      <div className="flex items-center gap-2">
        <Badge variant="outline" className="capitalize">
          {topic.difficulty}
        </Badge>
        <span className="font-mono text-xs text-muted-foreground">
          {Math.round(topic.suggestedDurationMs / 1000)} sec
        </span>
      </div>
      <h3 className="mt-4 text-lg font-semibold">
        <Link
          href={href as Route}
          className="focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none"
        >
          {topic.title}
        </Link>
      </h3>
      {topic.summary ? (
        <p className="mt-2 line-clamp-3 text-sm text-subtle-foreground">{topic.summary}</p>
      ) : null}
    </article>
  );
}
