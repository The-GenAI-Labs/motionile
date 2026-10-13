"use client";

import Link from "next/link";

import { StatusPage } from "@/components/shared/status-page";
import { Button } from "@/components/ui/button";

interface ErrorPageProps {
  error: Error & { digest?: string };
  reset: () => void;
}

export default function ErrorPage({ error, reset }: ErrorPageProps) {
  return (
    <StatusPage
      code={error.digest ? `Error reference ${error.digest}` : "Error"}
      title="Something went wrong"
      description="An unexpected error occurred. Please try again. If it keeps happening, contact support."
      actions={
        <>
          <Button
            onClick={() => {
              reset();
            }}
          >
            Try again
          </Button>
          <Button asChild variant="outline">
            <Link href="/">Back to home</Link>
          </Button>
        </>
      }
    />
  );
}
