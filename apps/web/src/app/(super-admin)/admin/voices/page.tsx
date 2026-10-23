import { PageHeader } from "@/components/shared/page-header";
import { SyncVoicesButton } from "@/features/admin-voices/components/sync-voices-button";
import { VoicesTable } from "@/features/admin-voices/components/voices-table";
import { requirePermissions } from "@/lib/auth/require-permissions";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata = buildMetadata({
  title: "Voice catalog",
  description:
    "Sync the built-in narration voices from the provider, curate their names, languages and tags, and choose which voices Motionile exposes to users.",
  path: "/admin/voices",
  noIndex: true,
});

export default async function AdminVoicesPage() {
  await requirePermissions(["voices.manage"]);
  return (
    <div className="space-y-8">
      <PageHeader
        title="Voice catalog"
        description="Built-in voices from the provider. New voices start hidden; expose a voice to offer it to users."
        actions={<SyncVoicesButton />}
      />
      <VoicesTable />
    </div>
  );
}
