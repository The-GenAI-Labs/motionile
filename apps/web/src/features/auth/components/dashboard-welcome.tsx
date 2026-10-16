"use client";

import Link from "next/link";

import { PageHeader } from "@/components/shared/page-header";
import { authErrorMessage } from "@/features/auth/errors";
import { useCurrentUser } from "@/features/auth/hooks/use-current-user";

export function DashboardWelcome() {
  const user = useCurrentUser();
  return (
    <div className="space-y-8">
      <PageHeader
        title={user.data?.name ? `Welcome, ${user.data.name}` : "Welcome to Motionile"}
        description="Your workspace is ready. Manage your account while we prepare the video creation experience."
      />
      {user.error ? <p role="alert">{authErrorMessage(user.error)}</p> : null}
      <Link
        href="/settings/security"
        className="inline-flex rounded-md border bg-surface px-4 py-3 text-sm font-medium hover:bg-elevated"
      >
        Manage account security
      </Link>
    </div>
  );
}
