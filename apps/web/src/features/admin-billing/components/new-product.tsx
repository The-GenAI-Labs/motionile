"use client";

import { useState } from "react";

import { Label } from "@/components/ui/label";
import { ProductCreateForm } from "@/features/admin-billing/components/product-form";
import { productKindLabels } from "@/features/admin-billing/schemas/admin-billing.schema";
import type { ProductKind } from "@/features/admin-billing/types/admin-billing.types";
import { usePermissions } from "@/features/auth/hooks/use-permissions";

const KINDS = ["credit_pack", "subscription"] as const satisfies readonly ProductKind[];

export function NewProduct() {
  const { can, isPending } = usePermissions();
  const [kind, setKind] = useState<ProductKind>("credit_pack");
  if (isPending) {
    return (
      <p role="status" className="text-sm text-muted-foreground">
        Loading
      </p>
    );
  }
  if (!can("billing.products.manage")) {
    return (
      <p role="note" className="rounded-xl border bg-surface p-6 text-sm text-muted-foreground">
        Creating products needs the billing.products.manage permission, which your account does not
        have.
      </p>
    );
  }
  return (
    <div className="space-y-6 rounded-xl border bg-surface p-6">
      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">Product type</legend>
        <div className="flex flex-wrap gap-4">
          {KINDS.map((option) => (
            <div key={option} className="flex items-center gap-2">
              <input
                type="radio"
                id={`product-kind-${option}`}
                name="product-kind"
                value={option}
                checked={kind === option}
                onChange={() => {
                  setKind(option);
                }}
                className="size-4 accent-primary focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none"
              />
              <Label htmlFor={`product-kind-${option}`}>{productKindLabels[option]}</Label>
            </div>
          ))}
        </div>
      </fieldset>
      <ProductCreateForm key={kind} kind={kind} />
    </div>
  );
}
