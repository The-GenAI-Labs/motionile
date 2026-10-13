"use client";

import { Loader2Icon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils/cn";

interface CursorPaginationProps {
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  fetchNextPage: () => unknown;
  loadMoreLabel?: string;
  endLabel?: string;
  className?: string;
}

export function CursorPagination({
  hasNextPage,
  isFetchingNextPage,
  fetchNextPage,
  loadMoreLabel = "Load more",
  endLabel = "You have reached the end of the list.",
  className,
}: CursorPaginationProps) {
  return (
    <div className={cn("flex justify-center py-4", className)}>
      {hasNextPage ? (
        <Button
          variant="outline"
          disabled={isFetchingNextPage}
          aria-busy={isFetchingNextPage}
          onClick={() => {
            if (!isFetchingNextPage) {
              void fetchNextPage();
            }
          }}
        >
          {isFetchingNextPage ? (
            <Loader2Icon aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
          ) : null}
          {loadMoreLabel}
        </Button>
      ) : (
        <p className="text-sm text-muted-foreground">{endLabel}</p>
      )}
    </div>
  );
}
