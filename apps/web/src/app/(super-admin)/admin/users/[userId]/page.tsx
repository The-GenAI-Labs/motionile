import { PageHeader } from "@/components/shared/page-header";
import { UserDetail } from "@/features/admin/components/user-detail";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata = buildMetadata({
  title: "User detail",
  description: "Review and manage a Motionile user.",
  path: "/admin/users",
  noIndex: true,
});

export default async function AdminUserPage({ params }: { params: Promise<{ userId: string }> }) {
  const { userId } = await params;
  return (
    <div className="space-y-8">
      <PageHeader
        title="User detail"
        description="Profile, roles, sessions, and administrative actions."
      />
      <UserDetail userId={userId} />
    </div>
  );
}
