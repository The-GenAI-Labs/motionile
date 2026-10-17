"use client";

import dynamic from "next/dynamic";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const AnalyticsChart = dynamic(() => import("@/features/admin/components/analytics-chart"), {
  ssr: false,
  loading: () => <div className="h-72 animate-pulse rounded-lg bg-elevated" />,
});

export interface AnalyticsOverviewData {
  totalUsers: number;
  verifiedRatio: number;
  activeSessions: number;
  newUsers: readonly { date: string; count: number }[];
  signInMethods: Readonly<Record<string, number>>;
}

export function AnalyticsOverview({ data }: { data: AnalyticsOverviewData }) {
  const cards = [
    { label: "Total users", value: data.totalUsers.toLocaleString() },
    { label: "Verified", value: `${Math.round(data.verifiedRatio * 100)}%` },
    { label: "Active sessions", value: data.activeSessions.toLocaleString() },
  ];
  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-3">
        {cards.map((card) => (
          <Card key={card.label}>
            <CardHeader>
              <CardTitle className="text-sm text-muted-foreground">{card.label}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="font-mono text-3xl font-semibold">{card.value}</p>
            </CardContent>
          </Card>
        ))}
      </div>
      <Card>
        <CardHeader>
          <CardTitle>New users</CardTitle>
        </CardHeader>
        <CardContent>
          <AnalyticsChart data={data.newUsers} />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Sign-in methods</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid gap-3 sm:grid-cols-3">
            {Object.entries(data.signInMethods).map(([method, count]) => (
              <div key={method} className="rounded-lg border p-4">
                <dt className="capitalize text-muted-foreground">{method}</dt>
                <dd className="mt-1 font-mono text-xl">{count}</dd>
              </div>
            ))}
          </dl>
        </CardContent>
      </Card>
    </div>
  );
}
