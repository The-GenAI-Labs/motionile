"use client";

import { XIcon } from "lucide-react";
import { useId } from "react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useCatalogSearch } from "@/features/catalog/hooks/use-catalog-search";
import {
  QUERY_MAX_CHARS,
  TOPIC_SEARCH_DEBOUNCE_MS,
} from "@/features/generation/schemas/generation.schema";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";

export interface SelectedTopic {
  id: string;
  title: string | null;
  suggestedDurationSeconds: number | null;
}

interface TopicFieldProps {
  query: string;
  onQueryChange: (query: string) => void;
  topic: SelectedTopic | null;
  onSelect: (topic: SelectedTopic) => void;
  onClear: () => void;
  notice?: string | null;
  error?: string | undefined;
}

const MAX_SUGGESTIONS = 5;
const MS_PER_SECOND = 1000;

function Suggestions({
  query,
  onSelect,
}: {
  query: string;
  onSelect: (topic: SelectedTopic) => void;
}) {
  const results = useCatalogSearch(query);
  const items = results.data?.items.slice(0, MAX_SUGGESTIONS) ?? [];
  if (query.length < 2) {
    return null;
  }
  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground" role="status">
        {results.isFetching
          ? "Looking for matching topics"
          : items.length > 0
            ? "Matching topics from the catalog"
            : "No catalog topic matches. Your own words will be used."}
      </p>
      {items.length > 0 ? (
        <ul aria-label="Topic suggestions" className="grid gap-2 sm:grid-cols-2">
          {items.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                onClick={() => {
                  onSelect({
                    id: item.id,
                    title: item.title,
                    suggestedDurationSeconds: Math.round(item.suggestedDurationMs / MS_PER_SECOND),
                  });
                }}
                className="w-full rounded-md border bg-surface px-3 py-2 text-left text-sm outline-none hover:bg-elevated focus-visible:ring-[3px] focus-visible:ring-ring"
              >
                <span className="block font-medium">{item.title}</span>
                {item.summary ? (
                  <span className="line-clamp-2 block text-xs text-subtle-foreground">
                    {item.summary}
                  </span>
                ) : null}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function TopicField({
  query,
  onQueryChange,
  topic,
  onSelect,
  onClear,
  notice = null,
  error,
}: TopicFieldProps) {
  const fieldId = useId();
  const errorId = useId();
  const settled = useDebouncedValue(query.trim(), TOPIC_SEARCH_DEBOUNCE_MS);
  if (topic !== null) {
    return (
      <div className="space-y-2">
        <p className="text-sm font-medium">Topic</p>
        <div className="flex items-center justify-between gap-3 rounded-md border bg-surface px-3 py-2">
          <p className="text-sm">{topic.title ?? "Catalog topic"}</p>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={onClear}
            aria-label="Clear topic"
          >
            <XIcon aria-hidden="true" /> Clear
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          Clear the topic to describe your own question instead.
        </p>
      </div>
    );
  }
  return (
    <div className="space-y-3">
      <div className="space-y-2">
        <Label htmlFor={fieldId}>What should the video explain?</Label>
        <Textarea
          id={fieldId}
          value={query}
          maxLength={QUERY_MAX_CHARS}
          rows={3}
          placeholder="For example: How does a hash map handle collisions?"
          aria-invalid={error !== undefined}
          aria-describedby={error ? errorId : undefined}
          onChange={(event) => {
            onQueryChange(event.target.value);
          }}
        />
        {notice ? (
          <p role="status" className="text-sm text-muted-foreground">
            {notice}
          </p>
        ) : null}
        {error ? (
          <p id={errorId} role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </div>
      <Suggestions query={settled} onSelect={onSelect} />
    </div>
  );
}
