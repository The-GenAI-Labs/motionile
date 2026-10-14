import type { ReactNode } from "react";

import { AppShell } from "@/components/layouts/app-shell";

export function AdminShell({ children }: Readonly<{ children: ReactNode }>) {
  return <AppShell area="admin">{children}</AppShell>;
}
