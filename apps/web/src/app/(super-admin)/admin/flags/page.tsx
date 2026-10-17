import { PageHeader } from "@/components/shared/page-header";
import { PermissionGate } from "@/components/shared/permission-gate";
import { FlagsManager } from "@/features/platform/components/flags-manager";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata = buildMetadata({
  title: "Feature flags",
  description: "Manage Motionile feature rollouts.",
  path: "/admin/flags",
  noIndex: true,
});

export default function AdminFlagsPage() {
  return (
    <div className="space-y-8">
      <PageHeader
        title="Feature flags"
        description="Control availability by rollout percentage, user and role."
      />
      <PermissionGate required={["flags.manage"]}>
        <FlagsManager />
      </PermissionGate>
    </div>
  );
}
