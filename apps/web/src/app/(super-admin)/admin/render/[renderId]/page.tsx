import { PageHeader } from "@/components/shared/page-header";
import { RenderMonitor } from "@/features/admin-render/components/render-monitor";
import { requirePermissions } from "@/lib/auth/require-permissions";
import { buildMetadata } from "@/lib/seo/metadata";
import { uuidParam } from "@/lib/utils/route-params";

export const metadata = buildMetadata({
  title: "Render progress",
  description:
    "Follow a test bed render live: stages, validation report, timings, errors and the finished video.",
  path: "/admin/render",
  noIndex: true,
});

export default async function AdminRenderDetailPage({
  params,
}: {
  params: Promise<{ renderId: string }>;
}) {
  await requirePermissions(["render.testbed"]);
  const { renderId } = await params;
  return (
    <div className="space-y-8">
      <PageHeader title="Render progress" description="Live status of this test bed render." />
      <RenderMonitor renderId={uuidParam(renderId)} />
    </div>
  );
}
