import { PageHeader } from "@/components/shared/page-header";
import { AnalyticsDashboard } from "@/features/admin/components/analytics-dashboard";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata = buildMetadata({
  title: "Admin",
  description: "Motionile administration.",
  path: "/admin",
  noIndex: true,
});

export default function AdminPage() {
  return (
    <div className="space-y-8">
      <PageHeader
        title="Overview"
        description="Current user growth, verification, sessions, and sign-in methods."
      />
      <AnalyticsDashboard />
    </div>
  );
}
