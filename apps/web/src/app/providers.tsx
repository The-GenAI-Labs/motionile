"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import type { ReactNode } from "react";

import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { SessionRuntime } from "@/features/auth/components/session-runtime";
import { getQueryClient } from "@/lib/query/query-client";

const ReactQueryDevtools =
  process.env.NODE_ENV === "development"
    ? dynamic(
        () => import("@tanstack/react-query-devtools").then((module) => module.ReactQueryDevtools),
        { ssr: false },
      )
    : null;

export function Providers({ children }: Readonly<{ children: ReactNode }>) {
  const queryClient = getQueryClient();
  return (
    <QueryClientProvider client={queryClient}>
      <SessionRuntime />
      <TooltipProvider>
        {children}
        <Toaster />
      </TooltipProvider>
      {ReactQueryDevtools ? <ReactQueryDevtools buttonPosition="bottom-left" /> : null}
    </QueryClientProvider>
  );
}
