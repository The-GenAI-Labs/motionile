import type { ReactNode } from "react";

import { AccountMenu } from "@/components/layouts/account-menu";
import { AppMobileNav } from "@/components/layouts/app-mobile-nav";
import { SidebarNav } from "@/components/layouts/sidebar-nav";
import { SiteLogo } from "@/components/layouts/site-logo";
import { MAIN_CONTENT_ID, SkipLink } from "@/components/layouts/skip-link";
import { Badge } from "@/components/ui/badge";
import { type AppArea, appNavigation } from "@/config/navigation";

interface AppShellProps {
  area: AppArea;
  children: ReactNode;
}

export function AppShell({ area, children }: AppShellProps) {
  const navigation = appNavigation[area];
  return (
    <div className="flex min-h-dvh">
      <SkipLink />
      <aside
        aria-label={`${navigation.label} sidebar`}
        className="sticky top-0 hidden h-dvh w-64 shrink-0 flex-col gap-6 border-r bg-surface px-4 py-5 lg:flex"
      >
        <div className="flex items-center gap-2 px-2">
          <SiteLogo />
          {area === "admin" ? <Badge variant="outline">Admin</Badge> : null}
        </div>
        <SidebarNav area={area} />
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-16 items-center justify-between gap-4 border-b bg-background/90 px-4 backdrop-blur sm:px-6">
          <div className="flex items-center gap-2">
            <AppMobileNav area={area} />
            <p className="text-sm font-medium text-subtle-foreground">{navigation.label}</p>
          </div>
          <AccountMenu area={area} />
        </header>
        <main id={MAIN_CONTENT_ID} tabIndex={-1} className="flex-1 px-4 py-8 outline-none sm:px-6">
          {children}
        </main>
      </div>
    </div>
  );
}
