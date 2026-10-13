"use client";

import "./globals.css";

interface GlobalErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
}

export default function GlobalError({ reset }: GlobalErrorProps) {
  return (
    <html lang="en">
      <body>
        <main className="mx-auto flex min-h-dvh max-w-xl flex-col items-start justify-center gap-6 px-6">
          <h1 className="text-3xl font-semibold tracking-tight">Something went wrong</h1>
          <p className="text-subtle-foreground">An unexpected error occurred. Please try again.</p>
          <button
            type="button"
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none"
            onClick={() => {
              reset();
            }}
          >
            Try again
          </button>
        </main>
      </body>
    </html>
  );
}
