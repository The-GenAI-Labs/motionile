"use client";

import { PlusIcon, XIcon } from "lucide-react";
import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { addTag } from "@/features/admin-voices/schemas/admin-voices.schema";

interface TagInputProps {
  label: string;
  value: readonly string[];
  onChange: (tags: string[]) => void;
}

export function TagInput({ label, value, onChange }: TagInputProps) {
  const inputId = useId();
  const messageId = useId();
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);

  const commit = () => {
    const result = addTag(value, draft);
    setError(result.error);
    if (result.error === null) {
      onChange(result.tags);
      setDraft("");
    }
  };

  return (
    <div className="space-y-2">
      <Label htmlFor={inputId}>{label}</Label>
      <div className="flex gap-2">
        <Input
          id={inputId}
          value={draft}
          autoComplete="off"
          aria-invalid={error !== null}
          aria-describedby={error === null ? undefined : messageId}
          onChange={(event) => {
            setDraft(event.target.value);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === ",") {
              event.preventDefault();
              commit();
            }
          }}
        />
        <Button type="button" variant="outline" onClick={commit}>
          <PlusIcon aria-hidden="true" /> Add tag
        </Button>
      </div>
      {error === null ? null : (
        <p id={messageId} role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {value.length === 0 ? null : (
        <ul aria-label={`${label} added`} className="flex flex-wrap gap-2">
          {value.map((tag) => (
            <li
              key={tag}
              className="inline-flex items-center gap-1 rounded-full border bg-surface py-0.5 pr-1 pl-3 text-xs"
            >
              {tag}
              <button
                type="button"
                aria-label={`Remove tag ${tag}`}
                className="grid size-5 place-items-center rounded-full hover:bg-elevated focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none"
                onClick={() => {
                  onChange(value.filter((existing) => existing !== tag));
                }}
              >
                <XIcon aria-hidden="true" className="size-3" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
