"use client";

import { LogOutIcon, RotateCcwIcon, ShieldAlertIcon, UserRoundCheckIcon } from "lucide-react";

import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  useAdminUser,
  useAdminUserAction,
  useAssignRole,
  useRemoveRole,
} from "@/features/admin/hooks/use-admin-users";
import { useRoles } from "@/features/admin/hooks/use-roles";
import { UserCredits } from "@/features/admin-billing/components/user-credits";
import { usePermissions } from "@/features/auth/hooks/use-permissions";

export function UserDetail({ userId }: { userId: string }) {
  const user = useAdminUser(userId);
  const roles = useRoles();
  const action = useAdminUserAction(userId);
  const assign = useAssignRole(userId);
  const remove = useRemoveRole(userId);
  const { can } = usePermissions();
  if (user.isPending || roles.isPending) return <p role="status">Loading user…</p>;
  if (user.isError || roles.isError)
    return (
      <p role="alert" className="text-destructive">
        User details could not be loaded.
      </p>
    );
  const selectedRoles = new Set(user.data.roles);
  const actionButton =
    user.data.status === "suspended" ? (
      <ConfirmDialog
        title="Unsuspend user?"
        description="The user will be able to sign in again."
        trigger={
          <Button variant="outline">
            <UserRoundCheckIcon aria-hidden="true" /> Unsuspend
          </Button>
        }
        confirmLabel="Unsuspend"
        onConfirm={() => action.mutateAsync("unsuspend")}
      />
    ) : user.data.status === "deleted" ? (
      <ConfirmDialog
        title="Restore user?"
        description="The account will be restored inside its 30-day recovery window."
        trigger={
          <Button variant="outline">
            <RotateCcwIcon aria-hidden="true" /> Restore
          </Button>
        }
        confirmLabel="Restore"
        onConfirm={() => action.mutateAsync("restore")}
      />
    ) : (
      <ConfirmDialog
        title="Suspend user?"
        description="All active sessions will be revoked immediately."
        trigger={
          <Button variant="destructive">
            <ShieldAlertIcon aria-hidden="true" /> Suspend
          </Button>
        }
        destructive
        confirmLabel="Suspend"
        onConfirm={() => action.mutateAsync("suspend")}
      />
    );
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap justify-end gap-2">
        {actionButton}
        <ConfirmDialog
          title="Force sign-out?"
          description="Every active session for this user will be revoked."
          trigger={
            <Button variant="outline">
              <LogOutIcon aria-hidden="true" /> Force sign-out
            </Button>
          }
          confirmLabel="Sign out user"
          onConfirm={() => action.mutateAsync("sign-out")}
        />
      </div>
      <Tabs defaultValue="profile">
        <TabsList>
          <TabsTrigger value="profile">Profile</TabsTrigger>
          <TabsTrigger value="roles">Roles</TabsTrigger>
          <TabsTrigger value="sessions">Sessions</TabsTrigger>
          <TabsTrigger value="audit">Audit</TabsTrigger>
          {can("billing.read") ? <TabsTrigger value="credits">Credits</TabsTrigger> : null}
        </TabsList>
        <TabsContent value="profile">
          <Card>
            <CardHeader>
              <CardTitle>{user.data.name ?? "Unnamed user"}</CardTitle>
            </CardHeader>
            <CardContent>
              <dl className="grid gap-4 sm:grid-cols-2">
                <div>
                  <dt className="text-sm text-muted-foreground">Status</dt>
                  <dd>{user.data.status}</dd>
                </div>
                <div>
                  <dt className="text-sm text-muted-foreground">Locale</dt>
                  <dd>{user.data.locale}</dd>
                </div>
                <div>
                  <dt className="text-sm text-muted-foreground">Joined</dt>
                  <dd>{new Date(user.data.createdAt).toLocaleString()}</dd>
                </div>
                <div>
                  <dt className="text-sm text-muted-foreground">Contacts</dt>
                  <dd>{user.data.contacts.map((contact) => contact.value).join(", ")}</dd>
                </div>
              </dl>
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="roles">
          <div className="space-y-3">
            {roles.data.roles.map((role) => (
              <label key={role.id} className="flex items-center gap-3 rounded-lg border p-4">
                <input
                  type="checkbox"
                  checked={selectedRoles.has(role.key)}
                  onChange={(event) => {
                    if (event.target.checked) assign.mutate(role.id);
                    else remove.mutate(role.id);
                  }}
                />
                <span>{role.name}</span>
              </label>
            ))}
          </div>
        </TabsContent>
        <TabsContent value="sessions">
          <Card>
            <CardContent>
              <p className="font-mono text-3xl">{user.data.activeSessionCount}</p>
              <p className="text-sm text-muted-foreground">Active sessions</p>
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="audit">
          {user.data.recentAudit.length === 0 ? (
            <p className="rounded-xl border bg-surface p-6 text-muted-foreground">
              No recent audit activity.
            </p>
          ) : (
            <ol className="space-y-3">
              {user.data.recentAudit.map((entry) => (
                <li key={entry.id} className="rounded-xl border bg-surface p-4">
                  <p className="font-mono text-sm">{entry.action}</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {new Date(entry.createdAt).toLocaleString()} · {entry.actorType}
                  </p>
                </li>
              ))}
            </ol>
          )}
        </TabsContent>
        {can("billing.read") ? (
          <TabsContent value="credits">
            <UserCredits userId={userId} />
          </TabsContent>
        ) : null}
      </Tabs>
    </div>
  );
}
