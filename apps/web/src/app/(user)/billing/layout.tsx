import type { ReactNode } from "react";

import { BillingNav } from "@/features/billing/components/billing-nav";

export default function BillingLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <div className="space-y-8">
      <BillingNav />
      {children}
    </div>
  );
}
