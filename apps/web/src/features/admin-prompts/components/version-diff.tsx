"use client";

import { useState } from "react";

import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import { DetailSection } from "@/features/admin-billing/components/detail-section";
import { DiffViewer } from "@/features/admin-prompts/components/diff-viewer";
import { adminPromptsErrorMessage } from "@/features/admin-prompts/errors";
import { usePromptDiff } from "@/features/admin-prompts/hooks/use-admin-prompts";
import type { PromptVersion } from "@/features/admin-prompts/types/admin-prompts.types";

interface VersionDiffProps {
  templateKey: string;
  versions: readonly PromptVersion[];
}

function VersionPicker({
  id,
  label,
  value,
  versions,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  versions: readonly PromptVersion[];
  onChange: (value: string) => void;
}) {
  return (
    <div className="space-y-1">
      <Label htmlFor={id}>{label}</Label>
      <NativeSelect
        id={id}
        value={value}
        onChange={(event) => {
          onChange(event.target.value);
        }}
      >
        <option value="">Choose a version</option>
        {versions.map((version) => (
          <option key={version.id} value={String(version.version)}>
            Version {version.version}
            {version.isActive ? " (active)" : ""}
          </option>
        ))}
      </NativeSelect>
    </div>
  );
}

export function VersionDiff({ templateKey, versions }: VersionDiffProps) {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const sameVersion = from !== "" && from === to;
  const request =
    from !== "" && to !== "" && !sameVersion
      ? { key: templateKey, from: Number(from), to: Number(to) }
      : null;
  const diff = usePromptDiff(request);
  return (
    <DetailSection title="Compare versions">
      <p className="text-sm text-muted-foreground">
        Prompt text is shown to super admins only, is never cached by the browser and each view is
        audited.
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        <VersionPicker
          id="diff-from"
          label="From version"
          value={from}
          versions={versions}
          onChange={setFrom}
        />
        <VersionPicker
          id="diff-to"
          label="To version"
          value={to}
          versions={versions}
          onChange={setTo}
        />
      </div>
      {sameVersion ? (
        <p role="alert" className="text-sm text-destructive">
          Choose two different versions to compare.
        </p>
      ) : null}
      {request === null ? null : diff.isPending ? (
        <Skeleton role="status" aria-hidden={false} aria-label="Loading diff" className="h-48" />
      ) : diff.isError ? (
        <p role="alert" className="text-sm text-destructive">
          {adminPromptsErrorMessage(diff.error)}
        </p>
      ) : (
        <DiffViewer diff={diff.data} />
      )}
    </DetailSection>
  );
}
