import { Suspense } from "react";

import { ForgotPasswordForm } from "@/features/auth/components/forgot-password-form";
import { buildMetadata } from "@/lib/seo/metadata";
export const metadata = buildMetadata({
  title: "Forgot password",
  description: "Request a secure code to reset your Motionile password.",
  path: "/forgot-password",
  noIndex: true,
});
export default function Page() {
  return (
    <Suspense fallback={<p role="status">Loading…</p>}>
      <ForgotPasswordForm />
    </Suspense>
  );
}
