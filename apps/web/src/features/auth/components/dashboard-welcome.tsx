"use client";

import Link from "next/link";

import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { authErrorMessage } from "@/features/auth/errors";
import { useCurrentUser } from "@/features/auth/hooks/use-current-user";
import { CreditsCard } from "@/features/credits/components/credits-card";
import { RecentVideos } from "@/features/library/components/recent-videos";

export function DashboardWelcome() {
  const user = useCurrentUser();
  return (
    <div className="space-y-8">
      <PageHeader
        title={user.data?.name ? `Welcome, ${user.data.name}` : "Welcome to Motionile"}
        description="Start with a topic from the catalog or create an explainer from your own idea."
        actions={
          <>
            <Button asChild variant="outline">
              <Link href="/explore">Explore topics</Link>
            </Button>
            <Button asChild>
              <Link href="/create">Create video</Link>
            </Button>
          </>
        }
      />
      {user.error ? <p role="alert">{authErrorMessage(user.error)}</p> : null}
      <div className="grid gap-4 md:grid-cols-2">
        <RecentVideos />
        <CreditsCard />
      </div>
    </div>
  );
}
