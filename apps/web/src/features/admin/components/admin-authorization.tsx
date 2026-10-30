"use client";

import type { ReactNode } from "react";

import { PermissionGate } from "@/components/shared/permission-gate";

const ADMIN_PERMISSIONS = [
  "users.read",
  "roles.read",
  "audit.read",
  "analytics.read",
  "settings.read",
  "flags.manage",
  "catalog.manage",
  "music.manage",
  "render.testbed",
  "voices.manage",
  "billing.read",
  "billing.products.manage",
  "billing.webhooks.manage",
  "jobs.read_all",
  "prompts.manage",
  "skills.manage",
  "evals.run",
] as const;

export function AdminAuthorization({ children }: { children: ReactNode }) {
  return (
    <PermissionGate
      required={ADMIN_PERMISSIONS}
      mode="any"
      fallback={
        <section className="rounded-xl border bg-surface p-6">
          <h1 className="text-2xl font-semibold">Access denied</h1>
          <p className="mt-2 text-subtle-foreground">
            Your account does not have access to the administration console.
          </p>
        </section>
      }
    >
      {children}
    </PermissionGate>
  );
}
