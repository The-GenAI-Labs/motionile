"use client";

import { Button } from "@/components/ui/button";

interface ErrorPageProps {
  error: Error & { digest?: string };
  reset: () => void;
}

export default function ErrorPage({ reset }: ErrorPageProps) {
  return (
    <main className="mx-auto flex min-h-dvh max-w-xl flex-col items-start justify-center gap-6 px-6">
      <h1 className="text-3xl font-semibold tracking-tight">Something went wrong</h1>
      <p className="text-subtle-foreground">An unexpected error occurred. Please try again.</p>
      <Button
        onClick={() => {
          reset();
        }}
      >
        Try again
      </Button>
    </main>
  );
}
