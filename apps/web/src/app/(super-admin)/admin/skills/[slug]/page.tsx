import { notFound } from "next/navigation";

import { PageHeader } from "@/components/shared/page-header";
import { SkillDetail } from "@/features/admin-skills/components/skill-detail";
import { skillSlugSchema } from "@/features/admin-skills/schemas/admin-skills.schema";
import { requirePermissions } from "@/lib/auth/require-permissions";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata = buildMetadata({
  title: "System skill",
  description:
    "Inspect one Motionile system skill: its layer, current version, token cost, embedding status and version history.",
  path: "/admin/skills",
  noIndex: true,
});

export default async function AdminSkillPage({ params }: { params: Promise<{ slug: string }> }) {
  await requirePermissions(["skills.manage"]);
  const parsed = skillSlugSchema.safeParse((await params).slug);
  if (!parsed.success) {
    notFound();
  }
  return (
    <div className="space-y-8">
      <PageHeader title={parsed.data} description="Metadata and version history." />
      <SkillDetail slug={parsed.data} />
    </div>
  );
}
