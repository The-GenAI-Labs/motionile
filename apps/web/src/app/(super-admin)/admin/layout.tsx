import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AdminShell } from "@/components/layouts/admin-shell";
import { AdminAuthorization } from "@/features/admin/components/admin-authorization";
import { SessionKeepalive } from "@/features/auth/components/session-keepalive";
import { protectedNextPath, requireRole, requireUser } from "@/lib/auth/guards";

export const metadata: Metadata = { robots: { index: false, follow: false } };

export default async function AdminLayout({ children }: Readonly<{ children: ReactNode }>) {
  const principal = await requireUser(await protectedNextPath("/admin"));
  requireRole(principal, ["super_admin"]);
  return (
    <AdminShell>
      <SessionKeepalive />
      <AdminAuthorization>{children}</AdminAuthorization>
    </AdminShell>
  );
}
