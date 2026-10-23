import Link from "next/link";

import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { VoiceGallery } from "@/features/voices/components/voice-gallery";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata = buildMetadata({
  title: "Voices",
  description:
    "Preview Motionile narration voices, choose your default voice and manage the voices you cloned from your own recordings.",
  path: "/settings/voices",
  noIndex: true,
});

export default function VoicesSettingsPage() {
  return (
    <div className="space-y-8">
      <PageHeader
        title="Voices"
        description="Preview the voices that narrate your videos, pick a default and manage voices cloned from your own."
        actions={
          <Button asChild variant="outline">
            <Link href={{ pathname: "/settings/voices/new" }}>Clone your voice</Link>
          </Button>
        }
      />
      <VoiceGallery />
    </div>
  );
}
