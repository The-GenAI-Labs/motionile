"use client";

import { PlusIcon, Trash2Icon } from "lucide-react";
import { useState } from "react";

import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { Button } from "@/components/ui/button";
import { RoleEditor } from "@/features/admin/components/role-editor";
import {
  useCreateRole,
  useDeleteRole,
  useRoles,
  useUpdateRole,
} from "@/features/admin/hooks/use-roles";
import { useCurrentUser } from "@/features/auth/hooks/use-current-user";

export function RolesManager() {
  const catalog = useRoles();
  const currentUser = useCurrentUser();
  const create = useCreateRole();
  const update = useUpdateRole();
  const remove = useDeleteRole();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  if (catalog.isPending) return <p role="status">Loading roles…</p>;
  if (catalog.isError)
    return (
      <p role="alert" className="text-destructive">
        Roles could not be loaded.
      </p>
    );
  const selected = catalog.data.roles.find((role) => role.id === selectedId);
  const newRole = selectedId === "new";
  return (
    <div className="grid gap-8 lg:grid-cols-[18rem_1fr]">
      <aside>
        <Button
          type="button"
          className="mb-4 w-full"
          onClick={() => {
            setSelectedId("new");
          }}
        >
          <PlusIcon aria-hidden="true" /> New role
        </Button>
        <ul className="space-y-2">
          {catalog.data.roles.map((role) => (
            <li key={role.id}>
              <button
                type="button"
                onClick={() => {
                  setSelectedId(role.id);
                }}
                className="w-full rounded-lg border bg-surface p-3 text-left hover:bg-elevated focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none"
              >
                <span className="block font-medium">{role.name}</span>
                <span className="font-mono text-xs text-muted-foreground">
                  {role.key} · {role.userCount} users
                </span>
              </button>
            </li>
          ))}
        </ul>
      </aside>
      <section aria-live="polite">
        {selected || newRole ? (
          <div className="space-y-6">
            <RoleEditor
              key={selected?.id ?? "new"}
              value={
                selected
                  ? {
                      key: selected.key,
                      name: selected.name,
                      description: selected.description ?? "",
                      permissions: selected.permissions,
                    }
                  : { key: "", name: "", description: "", permissions: [] }
              }
              permissions={catalog.data.permissions}
              grantablePermissions={currentUser.data?.permissions ?? []}
              systemRole={selected?.isSystem ?? false}
              onSave={async (value) => {
                if (selected) {
                  await update.mutateAsync({
                    roleId: selected.id,
                    input: {
                      name: value.name,
                      description: value.description || null,
                      permissions: [...value.permissions],
                    },
                  });
                } else {
                  const created = await create.mutateAsync({
                    key: value.key,
                    name: value.name,
                    description: value.description || null,
                    permissions: [...value.permissions],
                  });
                  setSelectedId(created.id);
                }
              }}
            />
            {selected && !selected.isSystem ? (
              <ConfirmDialog
                title="Delete role?"
                description="Only roles with no assigned users can be deleted."
                confirmLabel="Delete role"
                destructive
                trigger={
                  <Button variant="destructive">
                    <Trash2Icon aria-hidden="true" /> Delete role
                  </Button>
                }
                onConfirm={() =>
                  remove.mutateAsync(selected.id).then(() => {
                    setSelectedId(null);
                  })
                }
              />
            ) : null}
          </div>
        ) : (
          <p className="rounded-xl border bg-surface p-6 text-muted-foreground">
            Select a role to edit its permissions.
          </p>
        )}
      </section>
    </div>
  );
}
