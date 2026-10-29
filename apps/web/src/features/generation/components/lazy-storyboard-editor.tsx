"use client";

import dynamic from "next/dynamic";

import { LoadingSpinner } from "@/components/shared/loading-spinner";
import { Skeleton } from "@/components/ui/skeleton";

const editorLoading = () => (
  <div className="space-y-3">
    <Skeleton className="h-40 w-full" />
    <LoadingSpinner label="Loading the storyboard editor" />
  </div>
);

export const LazyStoryboardEditor = dynamic(
  () =>
    import("@/features/generation/components/storyboard-editor").then(
      (module) => module.StoryboardEditor,
    ),
  { ssr: false, loading: editorLoading },
);
