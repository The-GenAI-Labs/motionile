"use client";

import dynamic from "next/dynamic";

import { LoadingSpinner } from "@/components/shared/loading-spinner";
import { Skeleton } from "@/components/ui/skeleton";

const playerLoading = () => (
  <div className="space-y-3">
    <Skeleton className="aspect-video w-full" />
    <LoadingSpinner label="Loading video player" />
  </div>
);

export const LazyVideoPlayer = dynamic(
  () => import("@/features/library/components/video-player").then((module) => module.VideoPlayer),
  { ssr: false, loading: playerLoading },
);
