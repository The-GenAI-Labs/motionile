import { PageHeader } from "@/components/shared/page-header";
import { TemplatesTable } from "@/features/admin-prompts/components/templates-table";
import { requirePermissions } from "@/lib/auth/require-permissions";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata = buildMetadata({
  title: "Prompts",
  description:
    "Review the versioned system prompts that drive Motionile generation, their evaluation status and which version is active.",
  path: "/admin/prompts",
  noIndex: true,
});

export default async function AdminPromptsPage() {
  await requirePermissions(["prompts.manage"]);
  return (
    <div className="space-y-8">
      <PageHeader
        title="Prompts"
        description="Versioned system prompts. A version goes live only after its evaluation suites pass."
      />
      <TemplatesTable />
    </div>
  );
}
