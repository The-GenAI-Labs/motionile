import Link from "next/link";
import type { ReactNode } from "react";

import { siteConfig } from "@/config/site";

export default function PublicLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="border-b">
        <div className="mx-auto flex h-16 w-full max-w-6xl items-center px-6">
          <Link
            href="/"
            className="rounded-sm font-semibold tracking-tight focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none"
          >
            {siteConfig.name}
          </Link>
        </div>
      </header>
      <main id="main" className="flex-1">
        {children}
      </main>
      <footer className="border-t">
        <div className="mx-auto w-full max-w-6xl px-6 py-8 text-sm text-muted-foreground">
          © {new Date().getFullYear()} {siteConfig.name}
        </div>
      </footer>
    </div>
  );
}
