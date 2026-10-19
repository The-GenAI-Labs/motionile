"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { adminBillingNavigation, isActivePath } from "@/config/navigation";
import { usePermissions } from "@/features/auth/hooks/use-permissions";
import { cn } from "@/lib/utils/cn";

const ADMIN_BILLING_HOME = "/admin/billing";

export function AdminBillingNav() {
  const pathname = usePathname();
  const { can } = usePermissions();
  const items = adminBillingNavigation.filter((item) => can(item.permission));
  return (
    <nav aria-label="Billing administration">
      <ul className="flex flex-wrap gap-2 border-b pb-3">
        {items.map((item) => {
          const active = isActivePath(pathname, item.href, ADMIN_BILLING_HOME);
          return (
            <li key={item.href}>
              <Link
                href={{ pathname: item.href }}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "rounded-md px-3 py-2 text-sm text-subtle-foreground hover:bg-elevated hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none",
                  active && "bg-elevated text-foreground",
                )}
              >
                {item.title}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
