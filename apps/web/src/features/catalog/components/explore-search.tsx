"use client";

import { SearchIcon } from "lucide-react";
import { useDeferredValue, useState } from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { TopicCard } from "@/features/catalog/components/topic-card";
import { useCatalogSearch } from "@/features/catalog/hooks/use-catalog-search";

export function ExploreSearch() {
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query.trim());
  const results = useCatalogSearch(deferredQuery);
  return (
    <section aria-labelledby="topic-search-title" className="space-y-5">
      <div>
        <h2 id="topic-search-title" className="text-2xl font-semibold">
          Find a topic
        </h2>
        <Label htmlFor="topic-search" className="sr-only">
          Search topics
        </Label>
        <div className="relative mt-3 max-w-2xl">
          <SearchIcon
            aria-hidden="true"
            className="absolute top-3 left-3 size-4 text-muted-foreground"
          />
          <Input
            id="topic-search"
            type="search"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
            }}
            placeholder="Search concepts, subjects and skills"
            className="pl-9"
          />
        </div>
      </div>
      {results.isFetching ? (
        <p role="status" className="text-sm text-muted-foreground">
          Searching…
        </p>
      ) : null}
      {results.isError ? (
        <p role="alert" className="text-sm text-destructive">
          Search is unavailable right now.
        </p>
      ) : null}
      {results.data ? (
        results.data.items.length > 0 ? (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {results.data.items.map((topic) => (
              <TopicCard key={topic.id} topic={topic} href={topic.path} />
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">No topics matched “{deferredQuery}”.</p>
        )
      ) : null}
    </section>
  );
}
