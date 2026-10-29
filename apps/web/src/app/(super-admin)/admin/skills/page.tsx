import { PageHeader } from "@/components/shared/page-header";
import { SkillsOverview } from "@/features/admin-skills/components/skills-overview";
import { requirePermissions } from "@/lib/auth/require-permissions";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata = buildMetadata({
  title: "System skills",
  description:
    "Review the system skills that shape Motionile videos: layers, versions, token cost and embedding status, and reseed them from the shipped library.",
  path: "/admin/skills",
  noIndex: true,
});

export default async function AdminSkillsPage() {
  await requirePermissions(["skills.manage"]);
  return (
    <div className="space-y-8">
      <PageHeader
        title="System skills"
        description="The style, visual and domain skills that ship with Motionile. Their text is never shown."
      />
      <SkillsOverview />
    </div>
  );
}
