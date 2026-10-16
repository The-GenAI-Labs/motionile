import type { Metadata } from "next";
import type { ReactNode } from "react";

import { UserShell } from "@/components/layouts/user-shell";
import { SessionKeepalive } from "@/features/auth/components/session-keepalive";
import { protectedNextPath, requireUser } from "@/lib/auth/guards";

export const metadata: Metadata = { robots: { index: false, follow: false } };

export default async function UserLayout({ children }: Readonly<{ children: ReactNode }>) {
  await requireUser(await protectedNextPath("/dashboard"));
  return (
    <UserShell>
      <SessionKeepalive />
      {children}
    </UserShell>
  );
}
