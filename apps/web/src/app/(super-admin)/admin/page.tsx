import { PageHeader } from "@/components/shared/page-header";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata = buildMetadata({
  title: "Admin",
  description: "Motionile administration.",
  path: "/admin",
  noIndex: true,
});

export default function AdminPage() {
  return (
    <PageHeader
      title="Administration"
      description="Your administrator session is active. User and catalog management arrive in the next release."
    />
  );
}
