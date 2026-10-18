"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { billingNavigation, isActivePath } from "@/config/navigation";
import { cn } from "@/lib/utils/cn";

const BILLING_HOME = "/billing";

export function BillingNav() {
  const pathname = usePathname();
  return (
    <nav aria-label="Billing sections">
      <ul className="flex flex-wrap gap-2 border-b pb-3">
        {billingNavigation.map((item) => {
          const active = isActivePath(pathname, item.href, BILLING_HOME);
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
