import type { ReactNode } from "react";

import { AdminBillingNav } from "@/features/admin-billing/components/admin-billing-nav";

export default function AdminBillingLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <div className="space-y-8">
      <AdminBillingNav />
      {children}
    </div>
  );
}
