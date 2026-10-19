import { Button } from "@/components/ui/button";
import { billingErrorMessage } from "@/features/billing/errors";

interface BillingErrorProps {
  error: unknown;
  onRetry?: () => void;
}

export function BillingError({ error, onRetry }: BillingErrorProps) {
  return (
    <div role="alert" className="flex flex-wrap items-center gap-3 text-sm text-destructive">
      <p>{billingErrorMessage(error)}</p>
      {onRetry ? (
        <Button variant="outline" size="sm" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  );
}
