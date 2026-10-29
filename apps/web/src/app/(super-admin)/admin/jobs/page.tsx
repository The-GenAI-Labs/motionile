import { PageHeader } from "@/components/shared/page-header";
import { JobsAnalyticsPanel } from "@/features/admin-jobs/components/jobs-analytics";
import { JobsTable } from "@/features/admin-jobs/components/jobs-table";
import { requirePermissions } from "@/lib/auth/require-permissions";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata = buildMetadata({
  title: "Generation jobs",
  description:
    "Review every Motionile generation job across users, with outcomes, stage timings, repair and fallback rates, and provider cost.",
  path: "/admin/jobs",
  noIndex: true,
});

export default async function AdminJobsPage() {
  await requirePermissions(["jobs.read_all"]);
  return (
    <div className="space-y-8">
      <PageHeader
        title="Generation jobs"
        description="Every user's jobs, newest first, with the analytics for the selected range."
      />
      <JobsAnalyticsPanel />
      <JobsTable />
    </div>
  );
}
