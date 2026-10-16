import { PageHeader } from "@/components/shared/page-header";
import { ProfileSettings } from "@/features/users/components/profile-settings";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata = buildMetadata({
  title: "Profile settings",
  description: "Manage your Motionile profile, contacts and video preferences.",
  path: "/settings/profile",
  noIndex: true,
});

export default function ProfileSettingsPage() {
  return (
    <div className="space-y-8">
      <PageHeader
        title="Profile settings"
        description="Manage your profile, verified contacts and creation defaults."
      />
      <ProfileSettings />
    </div>
  );
}
