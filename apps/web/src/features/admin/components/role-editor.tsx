"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

export interface RoleEditorPermission {
  key: string;
  description: string | null;
}

export interface RoleEditorValue {
  key: string;
  name: string;
  description: string;
  permissions: readonly string[];
}

const groupPermissions = (permissions: readonly RoleEditorPermission[]) =>
  Object.groupBy(permissions, (permission) => permission.key.split(".")[0] ?? "other");

interface RoleEditorProps {
  value: RoleEditorValue;
  permissions: readonly RoleEditorPermission[];
  grantablePermissions: readonly string[];
  systemRole?: boolean;
  onSave: (value: RoleEditorValue) => Promise<void>;
}

export function RoleEditor({
  value,
  permissions,
  grantablePermissions,
  systemRole = false,
  onSave,
}: RoleEditorProps) {
  const [draft, setDraft] = useState(value);
  const [saving, setSaving] = useState(false);
  const groups = groupPermissions(permissions);
  const toggle = (permission: string, checked: boolean) => {
    setDraft({
      ...draft,
      permissions: checked
        ? [...new Set([...draft.permissions, permission])]
        : draft.permissions.filter((item) => item !== permission),
    });
  };
  return (
    <form
      className="space-y-6"
      onSubmit={(event) => {
        event.preventDefault();
        setSaving(true);
        void onSave(draft).finally(() => {
          setSaving(false);
        });
      }}
    >
      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <Label htmlFor="role-name">Name</Label>
          <Input
            id="role-name"
            value={draft.name}
            onChange={(event) => {
              setDraft({ ...draft, name: event.target.value });
            }}
            className="mt-1"
          />
        </div>
        <div>
          <Label htmlFor="role-key">Key</Label>
          <Input
            id="role-key"
            value={draft.key}
            disabled={systemRole}
            onChange={(event) => {
              setDraft({ ...draft, key: event.target.value });
            }}
            className="mt-1 font-mono"
          />
        </div>
      </div>
      <div>
        <Label htmlFor="role-description">Description</Label>
        <Textarea
          id="role-description"
          value={draft.description}
          onChange={(event) => {
            setDraft({ ...draft, description: event.target.value });
          }}
          className="mt-1"
        />
      </div>
      <fieldset className="space-y-5">
        <legend className="text-lg font-semibold">Permissions</legend>
        {Object.entries(groups).map(([group, items]) => (
          <div key={group} className="rounded-xl border bg-surface p-4">
            <h3 className="mb-3 capitalize">{group}</h3>
            <div className="grid gap-3 md:grid-cols-2">
              {items?.map((permission) => {
                const grantable = grantablePermissions.includes(permission.key);
                return (
                  <div key={permission.key} className="flex items-start gap-3">
                    <Checkbox
                      id={`permission-${permission.key}`}
                      checked={draft.permissions.includes(permission.key)}
                      disabled={!grantable}
                      onCheckedChange={(checked) => {
                        toggle(permission.key, checked === true);
                      }}
                    />
                    <div>
                      <Label htmlFor={`permission-${permission.key}`} className="font-mono text-sm">
                        {permission.key}
                      </Label>
                      <p className="text-xs text-muted-foreground">
                        {grantable
                          ? permission.description
                          : "You cannot grant a permission you do not hold."}
                      </p>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </fieldset>
      <Button type="submit" disabled={saving}>
        {saving ? "Saving…" : "Save role"}
      </Button>
    </form>
  );
}
