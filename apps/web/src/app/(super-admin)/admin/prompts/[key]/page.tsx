import { notFound } from "next/navigation";

import { PageHeader } from "@/components/shared/page-header";
import { TemplateDetail } from "@/features/admin-prompts/components/template-detail";
import { promptKeySchema } from "@/features/admin-prompts/schemas/admin-prompts.schema";
import { requirePermissions } from "@/lib/auth/require-permissions";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata = buildMetadata({
  title: "Prompt template",
  description:
    "Manage the versions of one Motionile system prompt: drafts, comparisons, evaluation runs, activation and rollback.",
  path: "/admin/prompts",
  noIndex: true,
});

export default async function AdminPromptTemplatePage({
  params,
}: {
  params: Promise<{ key: string }>;
}) {
  await requirePermissions(["prompts.manage"]);
  const parsed = promptKeySchema.safeParse((await params).key);
  if (!parsed.success) {
    notFound();
  }
  return (
    <div className="space-y-8">
      <PageHeader title={parsed.data} description="Versions, comparisons and evaluation runs." />
      <TemplateDetail templateKey={parsed.data} />
    </div>
  );
}
