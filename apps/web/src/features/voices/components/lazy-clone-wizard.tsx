"use client";

import dynamic from "next/dynamic";

import { LoadingSpinner } from "@/components/shared/loading-spinner";
import { Skeleton } from "@/components/ui/skeleton";

const wizardLoading = () => (
  <div className="space-y-3">
    <Skeleton className="h-64 w-full" />
    <LoadingSpinner label="Loading the voice cloning steps" />
  </div>
);

export const LazyCloneWizard = dynamic(
  () => import("@/features/voices/components/clone-wizard").then((module) => module.CloneWizard),
  { ssr: false, loading: wizardLoading },
);
