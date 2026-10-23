import { PageHeader } from "@/components/shared/page-header";
import { LazyCloneWizard } from "@/features/voices/components/lazy-clone-wizard";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata = buildMetadata({
  title: "Clone your voice",
  description:
    "Create a narration voice from your own recordings in four steps: consent, a spoken consent sentence, voice samples, and a name.",
  path: "/settings/voices/new",
  noIndex: true,
});

export default function NewVoicePage() {
  return (
    <div className="space-y-8">
      <PageHeader
        title="Clone your voice"
        description="Only clone your own voice. Your recordings stay private and are used only to create the voice."
      />
      <LazyCloneWizard />
    </div>
  );
}
