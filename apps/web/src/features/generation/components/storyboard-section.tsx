"use client";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { LazyStoryboardEditor } from "@/features/generation/components/lazy-storyboard-editor";
import { generationErrorMessage } from "@/features/generation/errors";
import { useStoryboard } from "@/features/generation/hooks/use-storyboard";

export function StoryboardSection({ jobId }: { jobId: string }) {
  const storyboard = useStoryboard(jobId, true);
  return (
    <section aria-labelledby="storyboard-heading" className="space-y-4">
      <div className="space-y-1">
        <h2 id="storyboard-heading" className="text-xl font-semibold">
          Review the storyboard
        </h2>
        <p className="text-sm text-subtle-foreground">
          Edit the scenes, reorder them or ask for a new plan. Nothing is recorded or rendered until
          you approve.
        </p>
      </div>
      {storyboard.isPending ? <Skeleton className="h-40 w-full" /> : null}
      {storyboard.isError ? (
        <div role="alert" className="space-y-2">
          <p className="text-sm text-destructive">{generationErrorMessage(storyboard.error)}</p>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              void storyboard.refetch();
            }}
          >
            Try again
          </Button>
        </div>
      ) : null}
      {storyboard.data ? (
        <LazyStoryboardEditor
          jobId={jobId}
          view={storyboard.data}
          onReload={async () => (await storyboard.refetch()).data}
        />
      ) : null}
    </section>
  );
}
