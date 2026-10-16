import { Suspense } from "react";

import { RegisterForm } from "@/features/auth/components/register-form";
import { buildMetadata } from "@/lib/seo/metadata";
export const metadata = buildMetadata({
  title: "Create account",
  description: "Create a Motionile account and verify your email or phone.",
  path: "/register",
  noIndex: true,
});
export default function Page() {
  return (
    <Suspense fallback={<p role="status">Loading…</p>}>
      <RegisterForm />
    </Suspense>
  );
}
