import { Suspense } from "react";

import { LoginForm } from "@/features/auth/components/login-form";
import { buildMetadata } from "@/lib/seo/metadata";
export const metadata = buildMetadata({
  title: "Login",
  description:
    "Sign in to your Motionile account using a password, one-time code or linked provider.",
  path: "/login",
  noIndex: true,
});
export default function Page() {
  return (
    <Suspense fallback={<p role="status">Loading…</p>}>
      <LoginForm />
    </Suspense>
  );
}
