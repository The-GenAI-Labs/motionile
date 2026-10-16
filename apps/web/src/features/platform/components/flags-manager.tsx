"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { EditableFlag } from "@/features/platform/components/flag-editor";
import { FlagEditor } from "@/features/platform/components/flag-editor";
import {
  useAdminFlags,
  useCreateFlag,
  useDeleteFlag,
  useUpdateFlag,
} from "@/features/platform/hooks/use-admin-platform";

export function FlagsManager() {
  const flags = useAdminFlags();
  const update = useUpdateFlag();
  const create = useCreateFlag();
  const remove = useDeleteFlag();
  const [key, setKey] = useState("");
  const [description, setDescription] = useState("");
  if (flags.isPending) return <p role="status">Loading feature flags…</p>;
  if (flags.isError)
    return (
      <p role="alert" className="text-destructive">
        Feature flags could not be loaded.
      </p>
    );
  const save = (flag: (typeof flags.data)[number], draft: EditableFlag) => {
    const rules: { kind: "user" | "role"; values: string[] }[] = [];
    if (draft.allowedUserIds.length)
      rules.push({ kind: "user", values: [...draft.allowedUserIds] });
    if (draft.allowedRoles.length) rules.push({ kind: "role", values: [...draft.allowedRoles] });
    return update
      .mutateAsync({
        key: draft.key,
        input: {
          enabled: draft.enabled,
          rolloutPercentage: draft.rolloutPercentage,
          description: flag.description,
          version: draft.version,
          rules,
        },
      })
      .then(() => undefined);
  };
  return (
    <div className="space-y-4">
      <form
        className="grid gap-4 rounded-xl border bg-surface p-5 md:grid-cols-[1fr_2fr_auto]"
        onSubmit={(event) => {
          event.preventDefault();
          create.mutate(
            { key, description, enabled: false, rolloutPercentage: 0, rules: [] },
            {
              onSuccess: () => {
                setKey("");
                setDescription("");
              },
            },
          );
        }}
      >
        <div>
          <Label htmlFor="new-flag-key">Flag key</Label>
          <Input
            id="new-flag-key"
            required
            value={key}
            onChange={(event) => {
              setKey(event.target.value);
            }}
          />
        </div>
        <div>
          <Label htmlFor="new-flag-description">Description</Label>
          <Input
            id="new-flag-description"
            required
            value={description}
            onChange={(event) => {
              setDescription(event.target.value);
            }}
          />
        </div>
        <Button className="self-end" type="submit" disabled={create.isPending}>
          Create flag
        </Button>
      </form>
      {flags.data.map((flag) => (
        <FlagEditor
          key={flag.key}
          flag={{
            key: flag.key,
            enabled: flag.enabled,
            rolloutPercentage: flag.rolloutPercentage,
            allowedUserIds: flag.rules
              .filter((rule) => rule.kind === "user")
              .flatMap((rule) => rule.values),
            allowedRoles: flag.rules
              .filter((rule) => rule.kind === "role")
              .flatMap((rule) => rule.values),
            version: flag.version,
          }}
          onSave={(draft) => save(flag, draft)}
          onDelete={() =>
            remove.mutateAsync({ key: flag.key, version: flag.version }).then(() => undefined)
          }
        />
      ))}
    </div>
  );
}
