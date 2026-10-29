import { PageHeader } from "@/components/shared/page-header";
import { JobDetail } from "@/features/admin-jobs/components/job-detail";
import { requirePermissions } from "@/lib/auth/require-permissions";
import { buildMetadata } from "@/lib/seo/metadata";
import { uuidParam } from "@/lib/utils/route-params";

export const metadata = buildMetadata({
  title: "Job detail",
  description:
    "Inspect one Motionile generation job: events, storyboard versions, scene attempts, validation reports and cost.",
  path: "/admin/jobs",
  noIndex: true,
});

export default async function AdminJobPage({ params }: { params: Promise<{ jobId: string }> }) {
  await requirePermissions(["jobs.read_all"]);
  const { jobId } = await params;
  return (
    <div className="space-y-8">
      <PageHeader title="Job" description="The full record of one generation job." />
      <JobDetail jobId={uuidParam(jobId)} />
    </div>
  );
}
