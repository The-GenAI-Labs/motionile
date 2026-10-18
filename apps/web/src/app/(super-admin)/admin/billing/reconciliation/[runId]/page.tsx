import { PageHeader } from "@/components/shared/page-header";
import { RunDetail } from "@/features/admin-billing/components/run-detail";
import { requirePermissions } from "@/lib/auth/require-permissions";
import { buildMetadata } from "@/lib/seo/metadata";
import { uuidParam } from "@/lib/utils/route-params";

export const metadata = buildMetadata({
  title: "Reconciliation run",
  description: "Review a Motionile reconciliation run and download its report.",
  path: "/admin/billing/reconciliation",
  noIndex: true,
});

export default async function BillingRunPage({ params }: { params: Promise<{ runId: string }> }) {
  await requirePermissions(["billing.read"]);
  const { runId } = await params;
  return (
    <div className="space-y-8">
      <PageHeader
        title="Reconciliation run"
        description="Counts, mismatches and the stored report of this run."
      />
      <RunDetail runId={uuidParam(runId)} />
    </div>
  );
}
