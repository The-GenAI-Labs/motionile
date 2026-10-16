import Link from "next/link";
import type { ReactNode } from "react";
export const metadata = { robots: { index: false, follow: false } };
export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-8 bg-background px-4 py-12">
      <Link href="/" className="text-2xl font-semibold tracking-tight">
        Motionile
      </Link>
      <div className="w-full max-w-md rounded-2xl border bg-surface p-6 sm:p-8">{children}</div>
      <nav aria-label="Legal" className="flex gap-5 text-sm text-muted-foreground">
        <Link href="/legal/terms" className="hover:text-foreground">
          Terms
        </Link>
        <Link href="/legal/privacy" className="hover:text-foreground">
          Privacy
        </Link>
      </nav>
    </main>
  );
}
