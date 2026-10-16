import Link from "next/link";
import type { ReactNode } from "react";

export default function SettingsLayout({ children }: { children: ReactNode }) {
  return (
    <div className="space-y-8">
      <nav aria-label="Account settings">
        <ul className="flex gap-2 border-b pb-3">
          <li>
            <Link
              href="/settings/profile"
              className="rounded-md px-3 py-2 text-sm hover:bg-elevated focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none"
            >
              Profile
            </Link>
          </li>
          <li>
            <Link
              href="/settings/security"
              className="rounded-md px-3 py-2 text-sm hover:bg-elevated focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none"
            >
              Security
            </Link>
          </li>
        </ul>
      </nav>
      {children}
    </div>
  );
}
