import type { ReactNode } from "react";

import { PublicFooter } from "@/components/layouts/public-footer";
import { PublicHeader } from "@/components/layouts/public-header";
import { MAIN_CONTENT_ID, SkipLink } from "@/components/layouts/skip-link";

export default function PublicLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <div className="flex min-h-dvh flex-col">
      <SkipLink />
      <PublicHeader />
      <main id={MAIN_CONTENT_ID} tabIndex={-1} className="flex-1 outline-none">
        {children}
      </main>
      <PublicFooter />
    </div>
  );
}
