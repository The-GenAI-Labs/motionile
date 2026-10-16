"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { type AppArea, appNavigation, isActivePath } from "@/config/navigation";
import { useCurrentUser } from "@/features/auth/hooks/use-current-user";
import { cn } from "@/lib/utils/cn";

interface SidebarNavProps {
  area: AppArea;
  onNavigate?: () => void;
}

export function SidebarNav({ area, onNavigate }: SidebarNavProps) {
  const pathname = usePathname();
  const navigation = appNavigation[area];
  const currentUser = useCurrentUser();
  const permissions = currentUser.data?.permissions ?? [];
  const items = navigation.items.filter(
    (item) =>
      area !== "admin" || item.permission === undefined || permissions.includes(item.permission),
  );
  return (
    <nav aria-label={navigation.label}>
      <ul className="flex flex-col gap-1">
        {items.map((item) => {
          const active = isActivePath(pathname, item.href, navigation.homeHref);
          const Icon = item.icon;
          return (
            <li key={item.href}>
              <Link
                href={{ pathname: item.href }}
                aria-current={active ? "page" : undefined}
                {...(onNavigate ? { onClick: onNavigate } : {})}
                className={cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm text-subtle-foreground transition-colors hover:bg-elevated hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none",
                  active && "bg-elevated text-foreground",
                )}
              >
                <Icon aria-hidden="true" className="size-4 shrink-0" />
                {item.title}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
