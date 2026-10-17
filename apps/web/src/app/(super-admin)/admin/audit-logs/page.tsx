import { PageHeader } from "@/components/shared/page-header";
import { AuditLog } from "@/features/admin/components/audit-log";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata = buildMetadata({
  title: "Audit logs",
  description: "Review Motionile administrative events.",
  path: "/admin/audit-logs",
  noIndex: true,
});

export default function AuditLogsPage() {
  return (
    <div className="space-y-8">
      <PageHeader
        title="Audit logs"
        description="Trace administrative and security-sensitive changes."
      />
      <AuditLog />
    </div>
  );
}
