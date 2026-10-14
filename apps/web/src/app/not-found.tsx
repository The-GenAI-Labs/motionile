import type { Metadata } from "next";
import Link from "next/link";

import { StatusPage } from "@/components/shared/status-page";
import { Button } from "@/components/ui/button";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata: Metadata = buildMetadata({
  title: "Page not found",
  description: "The page you are looking for does not exist or has moved.",
  path: "/404",
  noIndex: true,
});

export default function NotFound() {
  return (
    <StatusPage
      code="404"
      title="Page not found"
      description="The page you are looking for does not exist or has moved."
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
