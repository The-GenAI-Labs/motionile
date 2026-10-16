import Link from "next/link";

import { PageHeader } from "@/components/shared/page-header";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata = buildMetadata({
  title: "Access denied",
  description: "You do not have access to this Motionile page.",
  path: "/forbidden",
  noIndex: true,
});

export default function ForbiddenPage() {
  return (
    <div className="mx-auto max-w-xl space-y-6 px-6 py-24">
      <PageHeader
        title="Access denied"
        description="Your account does not have permission to view this page."
      />
      <Link href="/dashboard" className="underline underline-offset-4">
        Back to your dashboard
      </Link>
    </div>
  );
}
