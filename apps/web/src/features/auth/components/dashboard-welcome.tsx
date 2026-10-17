"use client";

import Link from "next/link";

import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { authErrorMessage } from "@/features/auth/errors";
import { useCurrentUser } from "@/features/auth/hooks/use-current-user";

export function DashboardWelcome() {
  const user = useCurrentUser();
  return (
    <div className="space-y-8">
      <PageHeader
        title={user.data?.name ? `Welcome, ${user.data.name}` : "Welcome to Motionile"}
        description="Start with a topic from the catalog or create an explainer from your own idea."
        actions={
          <Button asChild>
            <Link href="/explore">Explore topics</Link>
          </Button>
        }
      />
      {user.error ? <p role="alert">{authErrorMessage(user.error)}</p> : null}
      <div className="grid gap-4 md:grid-cols-2">
        <section className="rounded-xl border bg-surface p-6">
          <h2 className="font-semibold">Recent videos</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            Your generated videos will appear here.
          </p>
        </section>
        <section className="rounded-xl border bg-surface p-6">
          <h2 className="font-semibold">Credits</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            Credit usage will appear here when creation launches.
          </p>
        </section>
      </div>
    </div>
  );
}
