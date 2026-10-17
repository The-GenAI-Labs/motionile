"use client";

import { useState } from "react";

import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";

export interface EditableFlag {
  key: string;
  enabled: boolean;
  rolloutPercentage: number;
  allowedUserIds: readonly string[];
  allowedRoles: readonly string[];
  version: number;
}

export function FlagEditor({
  flag,
  onSave,
  onDelete,
}: {
  flag: EditableFlag;
  onSave: (flag: EditableFlag) => Promise<void>;
  onDelete: () => Promise<void>;
}) {
  const [draft, setDraft] = useState(flag);
  const [saving, setSaving] = useState(false);
  return (
    <form
      className="space-y-5 rounded-xl border bg-surface p-5"
      onSubmit={(event) => {
        event.preventDefault();
        setSaving(true);
        void onSave(draft).finally(() => {
          setSaving(false);
        });
      }}
    >
      <div className="flex items-center justify-between gap-4">
        <div>
          <h3 className="font-mono font-semibold">{draft.key}</h3>
          <p className="text-sm text-muted-foreground">Version {draft.version}</p>
        </div>
        <Switch
          aria-label={`Enable ${draft.key}`}
          checked={draft.enabled}
          onCheckedChange={(enabled) => {
            setDraft({ ...draft, enabled });
          }}
        />
      </div>
      <div>
        <div className="mb-2 flex justify-between">
          <Label htmlFor={`${draft.key}-rollout`}>Rollout</Label>
          <output>{draft.rolloutPercentage}%</output>
        </div>
        <Slider
          id={`${draft.key}-rollout`}
          min={0}
          max={100}
          step={1}
          value={[draft.rolloutPercentage]}
          onValueChange={([rolloutPercentage = 0]) => {
            setDraft({ ...draft, rolloutPercentage });
          }}
        />
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <Label htmlFor={`${draft.key}-users`}>Allowed user IDs</Label>
          <Input
            id={`${draft.key}-users`}
            value={draft.allowedUserIds.join(", ")}
            onChange={(event) => {
              setDraft({
                ...draft,
                allowedUserIds: event.target.value
                  .split(",")
                  .map((value) => value.trim())
                  .filter(Boolean),
              });
            }}
            className="mt-1"
          />
        </div>
        <div>
          <Label htmlFor={`${draft.key}-roles`}>Allowed roles</Label>
          <Input
            id={`${draft.key}-roles`}
            value={draft.allowedRoles.join(", ")}
            onChange={(event) => {
              setDraft({
                ...draft,
                allowedRoles: event.target.value
                  .split(",")
                  .map((value) => value.trim())
                  .filter(Boolean),
              });
            }}
            className="mt-1"
          />
        </div>
      </div>
      <div className="flex gap-2">
        <Button type="submit" disabled={saving}>
          {saving ? "Saving…" : "Save flag"}
        </Button>
        <ConfirmDialog
          title="Delete feature flag?"
          description="Clients will stop receiving this flag immediately."
          destructive
          confirmLabel="Delete flag"
          trigger={
            <Button type="button" variant="destructive">
              Delete
            </Button>
          }
          onConfirm={onDelete}
        />
      </div>
    </form>
  );
}
