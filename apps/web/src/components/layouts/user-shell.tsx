import type { ReactNode } from "react";

import { AppShell } from "@/components/layouts/app-shell";

export function UserShell({ children }: Readonly<{ children: ReactNode }>) {
  return <AppShell area="user">{children}</AppShell>;
}
