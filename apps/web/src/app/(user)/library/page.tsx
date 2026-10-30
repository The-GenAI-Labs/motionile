import Link from "next/link";

import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { LibraryView } from "@/features/library/components/library-view";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata = buildMetadata({
  title: "Library",
  description:
    "Your finished Motionile explainer videos: play them in every aspect ratio, share a public link, revise or delete them.",
  path: "/library",
  noIndex: true,
});

export default function LibraryPage() {
  return (
    <div className="space-y-8">
      <PageHeader
        title="Library"
        description="Your finished videos. Play, share, revise or delete them."
        actions={
          <Button asChild>
            <Link href="/create">Create video</Link>
          </Button>
        }
      />
      <LibraryView />
    </div>
  );
}
