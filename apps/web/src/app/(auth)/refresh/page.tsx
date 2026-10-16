import { Suspense } from "react";

import { RefreshSession } from "@/features/auth/components/refresh-session";
import { buildMetadata } from "@/lib/seo/metadata";
export const metadata = buildMetadata({
  title: "Restore session",
  description: "Securely restore your Motionile session and return to your work.",
  path: "/refresh",
  noIndex: true,
});
export default function Page() {
  return (
    <Suspense fallback={<p role="status">Loading…</p>}>
      <RefreshSession />
    </Suspense>
  );
}
