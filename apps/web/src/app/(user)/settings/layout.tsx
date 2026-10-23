import Link from "next/link";
import type { ReactNode } from "react";

import { settingsNavigation } from "@/config/navigation";

export default function SettingsLayout({ children }: { children: ReactNode }) {
  return (
    <div className="space-y-8">
      <nav aria-label="Account settings">
        <ul className="flex gap-2 border-b pb-3">
          {settingsNavigation.map((item) => (
            <li key={item.href}>
              <Link
                href={{ pathname: item.href }}
                className="rounded-md px-3 py-2 text-sm hover:bg-elevated focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none"
              >
                {item.title}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
      {children}
    </div>
  );
}
