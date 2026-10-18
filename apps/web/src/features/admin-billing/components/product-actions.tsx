"use client";

import { PauseIcon, PlayIcon, RefreshCwIcon } from "lucide-react";
import { type ReactNode, useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { Button } from "@/components/ui/button";
import { DuplicateProductDialog } from "@/features/admin-billing/components/duplicate-product-dialog";
import { adminBillingErrorMessage } from "@/features/admin-billing/errors";
import {
  type ProductAction,
  useProductAction,
} from "@/features/admin-billing/hooks/use-admin-products";
import type { AdminProductDetail } from "@/features/admin-billing/types/admin-billing.types";

interface ProductActionDialogProps {
  product: AdminProductDetail;
  action: ProductAction;
  title: string;
  description: string;
  confirmLabel: string;
  success: string;
  destructive?: boolean;
  children: ReactNode;
}

function ProductActionDialog({
  product,
  action,
  title,
  description,
  confirmLabel,
  success,
  destructive = false,
  children,
}: ProductActionDialogProps) {
  const mutation = useProductAction(product.id);
  const [open, setOpen] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  return (
    <ConfirmDialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) {
          setFailure(null);
        }
      }}
      trigger={children}
      title={title}
      description={description}
      confirmLabel={confirmLabel}
      destructive={destructive}
      error={failure === null ? null : adminBillingErrorMessage(failure)}
      onConfirm={async () => {
        setFailure(null);
        try {
          await mutation.mutateAsync(action);
        } catch (error) {
          setFailure(error);
          throw error;
        }
        toast.success(success);
      }}
    />
  );
}

export function ProductActions({ product }: { product: AdminProductDetail }) {
  const needsPlanSync = product.kind === "subscription" && product.razorpayPlanId === null;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {product.isActive ? (
          <ProductActionDialog
            product={product}
            action="deactivate"
            title="Deactivate this product?"
            description="It disappears from the pricing page and can no longer be bought. Existing orders and subscribers are not affected."
            confirmLabel="Deactivate"
            success="Product deactivated"
            destructive
          >
            <Button variant="outline">
              <PauseIcon aria-hidden="true" /> Deactivate
            </Button>
          </ProductActionDialog>
        ) : (
          <ProductActionDialog
            product={product}
            action="activate"
            title="Activate this product?"
            description="It appears on the pricing page and customers can buy it straight away."
            confirmLabel="Activate"
            success="Product activated"
          >
            <Button>
              <PlayIcon aria-hidden="true" /> Activate
            </Button>
          </ProductActionDialog>
        )}
        {needsPlanSync ? (
          <ProductActionDialog
            product={product}
            action="sync-plan"
            title="Sync the Razorpay plan?"
            description="Creates the plan at Razorpay from this product and links it. If Razorpay fails in an unclear way a plan may exist unlinked, and trying again creates a fresh plan."
            confirmLabel="Sync plan"
            success="Razorpay plan synced"
          >
            <Button variant="outline">
              <RefreshCwIcon aria-hidden="true" /> Sync plan
            </Button>
          </ProductActionDialog>
        ) : null}
        <DuplicateProductDialog product={product} />
      </div>
      {needsPlanSync ? (
        <p role="note" className="text-sm text-muted-foreground">
          This plan is not synced to Razorpay yet. Sync it before activating the product.
        </p>
      ) : null}
    </div>
  );
}
