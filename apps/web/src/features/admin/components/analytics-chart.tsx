"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export interface DailyUsersPoint {
  date: string;
  count: number;
}

export default function AnalyticsChart({ data }: { data: readonly DailyUsersPoint[] }) {
  return (
    <div className="h-72 w-full" role="img" aria-label="New users during the last 30 days">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={[...data]} margin={{ top: 12, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="var(--border)" vertical={false} />
          <XAxis dataKey="date" stroke="var(--text-muted)" tickLine={false} axisLine={false} />
          <YAxis
            stroke="var(--text-muted)"
            tickLine={false}
            axisLine={false}
            allowDecimals={false}
          />
          <Tooltip
            contentStyle={{
              background: "var(--elevated)",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius)",
            }}
          />
          <Area type="monotone" dataKey="count" stroke="var(--text)" fill="var(--border)" />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
