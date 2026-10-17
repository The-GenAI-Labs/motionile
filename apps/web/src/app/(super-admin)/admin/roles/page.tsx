import { PageHeader } from "@/components/shared/page-header";
import { PermissionGate } from "@/components/shared/permission-gate";
import { RolesManager } from "@/features/admin/components/roles-manager";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata = buildMetadata({
  title: "Roles",
  description: "Manage Motionile roles and permissions.",
  path: "/admin/roles",
  noIndex: true,
});

export default function AdminRolesPage() {
  return (
    <div className="space-y-8">
      <PageHeader
        title="Roles"
        description="Create scoped roles and grant only permissions you hold."
      />
      <PermissionGate required={["roles.read"]}>
        <RolesManager />
      </PermissionGate>
    </div>
  );
}
