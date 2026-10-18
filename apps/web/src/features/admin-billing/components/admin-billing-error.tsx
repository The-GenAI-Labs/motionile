import { Button } from "@/components/ui/button";
import { adminBillingErrorMessage } from "@/features/admin-billing/errors";

interface AdminBillingErrorProps {
  error: unknown;
  onRetry?: () => void;
}

export function AdminBillingError({ error, onRetry }: AdminBillingErrorProps) {
  return (
    <div role="alert" className="flex flex-wrap items-center gap-3 text-sm text-destructive">
      <p>{adminBillingErrorMessage(error)}</p>
      {onRetry ? (
        <Button variant="outline" size="sm" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  );
}

export function LoadingBlock({ label }: { label: string }) {
  return (
    <p role="status" className="text-sm text-muted-foreground">
      {label}
    </p>
  );
}
