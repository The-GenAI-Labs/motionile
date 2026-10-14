import { Loader2Icon } from "lucide-react";

import { cn } from "@/lib/utils/cn";

interface LoadingSpinnerProps {
  label?: string;
  showLabel?: boolean;
  className?: string;
}

export function LoadingSpinner({
  label = "Loading",
  showLabel = false,
  className,
}: LoadingSpinnerProps) {
  return (
    <span
      role="status"
      aria-live="polite"
      className={cn("inline-flex items-center gap-2 text-sm text-muted-foreground", className)}
    >
      <Loader2Icon aria-hidden="true" className="size-4 animate-spin motion-reduce:animate-none" />
      <span className={showLabel ? undefined : "sr-only"}>{label}</span>
    </span>
  );
}
