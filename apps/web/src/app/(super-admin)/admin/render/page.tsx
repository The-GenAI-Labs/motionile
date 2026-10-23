import { PageHeader } from "@/components/shared/page-header";
import { GoldenList } from "@/features/admin-render/components/golden-list";
import { UploadRenderForm } from "@/features/admin-render/components/upload-render-form";
import { requirePermissions } from "@/lib/auth/require-permissions";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata = buildMetadata({
  title: "Render test bed",
  description:
    "Upload a composition with narration, or render a golden composition, and watch the Motionile render pipeline validate and encode it.",
  path: "/admin/render",
  noIndex: true,
});

export default async function AdminRenderPage() {
  await requirePermissions(["render.testbed"]);
  return (
    <div className="space-y-12">
      <PageHeader
        title="Render test bed"
        description="Run a composition through the real render pipeline. Renders here charge no credits."
      />
      <section aria-labelledby="upload-heading" className="space-y-5">
        <h2 id="upload-heading" className="text-2xl font-semibold">
          Upload a composition
        </h2>
        <UploadRenderForm />
      </section>
      <section aria-labelledby="golden-heading" className="space-y-5">
        <h2 id="golden-heading" className="text-2xl font-semibold">
          Golden compositions
        </h2>
        <GoldenList />
      </section>
    </div>
  );
}
