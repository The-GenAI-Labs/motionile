"use client";

import "./globals.css";

import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import Link from "next/link";

import { StatusPage } from "@/components/shared/status-page";
import { Button } from "@/components/ui/button";

interface GlobalErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
}

export default function GlobalError({ error, reset }: GlobalErrorProps) {
  return (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <head>
        <title>Something went wrong · Motionile</title>
        <meta name="robots" content="noindex, nofollow" />
      </head>
      <body>
        <StatusPage
          code={error.digest ? `Error reference ${error.digest}` : "Error"}
          title="Something went wrong"
          description="Motionile hit an unexpected error while loading this page. Please try again."
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
      </body>
    </html>
  );
}
