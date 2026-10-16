import { PageHeader } from "@/components/shared/page-header";
import { UsersTable } from "@/features/admin/components/users-table";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata = buildMetadata({
  title: "Users",
  description: "Manage Motionile users.",
  path: "/admin/users",
  noIndex: true,
});

export default function AdminUsersPage() {
  return (
    <div className="space-y-8">
      <PageHeader
        title="Users"
        description="Search users, review access, and manage account status."
      />
      <UsersTable />
    </div>
  );
}
