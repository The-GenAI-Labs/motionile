import type { Metadata } from "next";
import Link from "next/link";

import { StatusPage } from "@/components/shared/status-page";
import { Button } from "@/components/ui/button";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata: Metadata = buildMetadata({
  title: "Access denied",
  description: "You do not have permission to view this page.",
  path: "/403",
  noIndex: true,
});

export default function Forbidden() {
  return (
    <StatusPage
      code="403"
      title="Access denied"
      description="You do not have permission to view this page. If you think this is a mistake, contact support."
      actions={
        <>
          <Button asChild>
            <Link href="/">Back to home</Link>
          </Button>
          <Button asChild variant="outline">
            <Link href="/contact">Contact support</Link>
          </Button>
        </>
      }
    />
  );
}
