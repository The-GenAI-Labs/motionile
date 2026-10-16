import { Suspense } from "react";

import { ResetPasswordForm } from "@/features/auth/components/reset-password-form";
import { buildMetadata } from "@/lib/seo/metadata";
export const metadata = buildMetadata({
  title: "Reset password",
  description: "Choose a new password for your Motionile account using your reset code.",
  path: "/reset-password",
  noIndex: true,
});
export default function Page() {
  return (
    <Suspense fallback={<p role="status">Loading…</p>}>
      <ResetPasswordForm />
    </Suspense>
  );
}
