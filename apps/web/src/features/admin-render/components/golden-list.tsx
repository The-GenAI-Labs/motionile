"use client";

import { EmptyState } from "@/components/shared/empty-state";
import { LoadingSpinner } from "@/components/shared/loading-spinner";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { GoldenRenderDialog } from "@/features/admin-render/components/golden-render-dialog";
import { adminRenderErrorMessage } from "@/features/admin-render/errors";
import { useGoldenCompositions } from "@/features/admin-render/hooks/use-testbed";

export function GoldenList() {
  const golden = useGoldenCompositions();

  if (golden.isPending) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-40" />
        <LoadingSpinner label="Loading golden compositions" />
      </div>
    );
  }
  if (golden.isError) {
    return (
      <div role="alert" className="flex flex-wrap items-center gap-3 text-sm text-destructive">
        <p>{adminRenderErrorMessage(golden.error)}</p>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            void golden.refetch();
          }}
        >
          Try again
        </Button>
      </div>
    );
  }
  if (golden.data.length === 0) {
    return (
      <EmptyState
        headingLevel={3}
        title="No golden compositions"
        description="The server has no golden compositions configured."
      />
    );
  }
  return (
    <ul aria-label="Golden compositions" className="grid gap-4 md:grid-cols-2">
      {golden.data.map((item) => (
        <li key={item.name} className="flex flex-col gap-3 rounded-xl border bg-surface p-4">
          <div className="space-y-1">
            <h3 className="font-medium">{item.title}</h3>
            <p className="text-sm text-subtle-foreground">{item.description}</p>
          </div>
          <p className="text-xs text-muted-foreground">
            {`Scenes: `}
            <span className="font-mono">{item.sceneIds.join(", ")}</span>
          </p>
          <div className="mt-auto">
            <GoldenRenderDialog golden={item} />
          </div>
        </li>
      ))}
    </ul>
  );
}
