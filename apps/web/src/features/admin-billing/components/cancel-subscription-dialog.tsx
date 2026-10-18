"use client";

import { BanIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { adminBillingErrorMessage } from "@/features/admin-billing/errors";
import { useCancelSubscription } from "@/features/admin-billing/hooks/use-admin-subscriptions";
import type { AdminSubscriptionDetail } from "@/features/admin-billing/types/admin-billing.types";

interface CancelSubscriptionDialogProps {
  subscription: AdminSubscriptionDetail;
}

export function CancelSubscriptionDialog({ subscription }: CancelSubscriptionDialogProps) {
  const cancel = useCancelSubscription(subscription.id);
  const [immediately, setImmediately] = useState(false);
  const [open, setOpen] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  return (
    <ConfirmDialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) {
          setImmediately(false);
          setFailure(null);
        }
      }}
      trigger={
        <Button variant="destructive">
          <BanIcon aria-hidden="true" /> Cancel subscription
        </Button>
      }
      title="Cancel this subscription?"
      description="Cancelling stops future charges. It does not refund any payment, and refunding a payment does not cancel the subscription."
      destructive
      confirmLabel={immediately ? "Cancel immediately" : "Cancel at period end"}
      error={failure === null ? null : adminBillingErrorMessage(failure)}
      onConfirm={async () => {
        setFailure(null);
        try {
          await cancel.mutateAsync(immediately);
        } catch (error) {
          setFailure(error);
          throw error;
        }
        toast.success(immediately ? "Subscription cancelled" : "Subscription set to end");
      }}
    >
      <div className="flex items-start gap-3">
        <Checkbox
          id={`cancel-immediately-${subscription.id}`}
          checked={immediately}
          onCheckedChange={(checked) => {
            setImmediately(checked === true);
          }}
        />
        <div className="grid gap-1">
          <Label htmlFor={`cancel-immediately-${subscription.id}`}>Cancel immediately</Label>
          <p className="text-sm text-muted-foreground">
            Without this, an active subscription ends when its paid period ends. A subscription that
            is not active has nothing to wait for and is cancelled immediately either way.
          </p>
        </div>
      </div>
    </ConfirmDialog>
  );
}
