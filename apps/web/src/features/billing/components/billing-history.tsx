"use client";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { OrdersTable } from "@/features/billing/components/orders-table";
import { LedgerTable } from "@/features/credits/components/ledger-table";
import { UsageView } from "@/features/credits/components/usage-view";

export function BillingHistory() {
  return (
    <Tabs defaultValue="payments" className="gap-4">
      <TabsList aria-label="History views">
        <TabsTrigger value="payments">Payments and orders</TabsTrigger>
        <TabsTrigger value="ledger">Credit ledger</TabsTrigger>
        <TabsTrigger value="usage">Usage</TabsTrigger>
      </TabsList>
      <TabsContent value="payments" className="space-y-3">
        <p className="text-sm text-muted-foreground">
          All amounts are in INR and include GST. Payment receipts are sent by email.
        </p>
        <OrdersTable />
      </TabsContent>
      <TabsContent value="ledger" className="space-y-3">
        <p className="text-sm text-muted-foreground">
          Every change to your credits, newest first. Reserved credits are held for work in
          progress.
        </p>
        <LedgerTable />
      </TabsContent>
      <TabsContent value="usage" className="space-y-3">
        <p className="text-sm text-muted-foreground">Credits spent on videos and publishing.</p>
        <UsageView />
      </TabsContent>
    </Tabs>
  );
}
