import { PageHeader } from "@/components/shared/page-header";
import { MusicTable } from "@/features/admin-music/components/music-table";
import { UploadTrackDialog } from "@/features/admin-music/components/upload-track-dialog";
import { requirePermissions } from "@/lib/auth/require-permissions";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata = buildMetadata({
  title: "Music library",
  description:
    "Upload, license and activate the background music tracks that Motionile offers for narrated explainer videos.",
  path: "/admin/music",
  noIndex: true,
});

export default async function AdminMusicPage() {
  await requirePermissions(["music.manage"]);
  return (
    <div className="space-y-8">
      <PageHeader
        title="Music library"
        description="Licensed background tracks. Only active tracks can be used in new renders."
        actions={<UploadTrackDialog />}
      />
      <MusicTable />
    </div>
  );
}
