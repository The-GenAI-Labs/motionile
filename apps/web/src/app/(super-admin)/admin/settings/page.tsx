import { PageHeader } from "@/components/shared/page-header";
import { PermissionGate } from "@/components/shared/permission-gate";
import { SettingsManager } from "@/features/platform/components/settings-manager";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata = buildMetadata({
  title: "System settings",
  description: "Manage Motionile runtime system settings.",
  path: "/admin/settings",
  noIndex: true,
});

export default function AdminSettingsPage() {
  return (
    <div className="space-y-8">
      <PageHeader
        title="System settings"
        description="Validated runtime values take effect without a deploy."
      />
      <PermissionGate required={["settings.read"]}>
        <SettingsManager />
      </PermissionGate>
    </div>
  );
}
