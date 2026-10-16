import { Suspense } from "react";

import { VerifyForm } from "@/features/auth/components/verify-form";
import { buildMetadata } from "@/lib/seo/metadata";
export const metadata = buildMetadata({
  title: "Verify your contact",
  description: "Verify your contact with a secure one-time code to continue to Motionile.",
  path: "/verify",
  noIndex: true,
});
export default function Page() {
  return (
    <Suspense fallback={<p role="status">Loading…</p>}>
      <VerifyForm />
    </Suspense>
  );
}
