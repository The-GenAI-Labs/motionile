"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2Icon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Form } from "@/components/ui/form";
import {
  ImmutabilityNotice,
  ProductFields,
} from "@/features/admin-billing/components/product-fields";
import { adminBillingErrorMessage, hasErrorCode } from "@/features/admin-billing/errors";
import {
  useCreateProduct,
  useUpdateProduct,
} from "@/features/admin-billing/hooks/use-admin-products";
import { adminBillingPaths } from "@/features/admin-billing/paths";
import {
  emptyProductFormValues,
  productFormSchema,
  type ProductFormValues,
  productFormValues,
  toCreateProductRequest,
  toUpdateProductRequest,
} from "@/features/admin-billing/schemas/admin-billing.schema";
import type {
  AdminProductDetail,
  ProductKind,
} from "@/features/admin-billing/types/admin-billing.types";

interface SubmitButtonProps {
  pending: boolean;
  label: string;
  disabled?: boolean;
}

function SubmitButton({ pending, label, disabled = false }: SubmitButtonProps) {
  return (
    <Button type="submit" disabled={pending || disabled} aria-busy={pending}>
      {pending ? (
        <Loader2Icon aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
      ) : null}
      {label}
    </Button>
  );
}

export function ProductCreateForm({ kind }: { kind: ProductKind }) {
  const router = useRouter();
  const create = useCreateProduct();
  const [failure, setFailure] = useState<unknown>(null);
  const form = useForm<ProductFormValues>({
    resolver: zodResolver(productFormSchema),
    defaultValues: emptyProductFormValues(kind),
  });
  const submit = form.handleSubmit(async (values) => {
    setFailure(null);
    try {
      const product = await create.mutateAsync(toCreateProductRequest(values));
      toast.success(`Created ${product.name}`);
      router.push(adminBillingPaths.product(product.id));
    } catch (error) {
      if (hasErrorCode(error, "product_code_exists")) {
        form.setError("code", { message: adminBillingErrorMessage(error) });
      } else {
        setFailure(error);
      }
    }
  });
  return (
    <Form {...form}>
      <form
        className="space-y-6"
        onSubmit={(event) => {
          void submit(event);
        }}
      >
        <ImmutabilityNotice inUse={false} />
        <ProductFields form={form} kind={kind} mode="create" financialLocked={false} />
        {kind === "subscription" ? (
          <p role="note" className="rounded-md border bg-elevated p-3 text-sm">
            Subscription products are created inactive. After creating it, sync the Razorpay plan,
            then activate the product.
          </p>
        ) : null}
        {failure === null ? null : (
          <p role="alert" className="text-sm text-destructive">
            {adminBillingErrorMessage(failure)}
          </p>
        )}
        <SubmitButton pending={create.isPending} label="Create product" />
      </form>
    </Form>
  );
}

interface ProductEditFormProps {
  product: AdminProductDetail;
  onReload: () => void;
}

export function ProductEditForm({ product, onReload }: ProductEditFormProps) {
  const update = useUpdateProduct(product.id);
  const [failure, setFailure] = useState<unknown>(null);
  const financialLocked = product.isUsed;
  const form = useForm<ProductFormValues>({
    resolver: zodResolver(productFormSchema),
    defaultValues: productFormValues(product),
  });
  const conflict = hasErrorCode(failure, "product_version_conflict");
  const submit = form.handleSubmit(async (values) => {
    setFailure(null);
    try {
      await update.mutateAsync(toUpdateProductRequest(values, product, financialLocked));
      toast.success("Product saved");
    } catch (error) {
      setFailure(error);
    }
  });
  return (
    <Form {...form}>
      <form
        className="space-y-6"
        aria-label="Edit product"
        onSubmit={(event) => {
          void submit(event);
        }}
      >
        <ImmutabilityNotice inUse={financialLocked} />
        <ProductFields
          form={form}
          kind={product.kind}
          mode="edit"
          financialLocked={financialLocked}
        />
        {failure === null ? null : (
          <div role="alert" className="flex flex-wrap items-center gap-3 text-sm text-destructive">
            <p>{adminBillingErrorMessage(failure)}</p>
            {conflict ? (
              <Button type="button" variant="outline" size="sm" onClick={onReload}>
                Reload latest version
              </Button>
            ) : null}
          </div>
        )}
        <div className="flex items-center gap-3">
          <SubmitButton
            pending={update.isPending}
            disabled={conflict || !form.formState.isDirty}
            label="Save changes"
          />
          <span className="text-sm text-muted-foreground">Version {product.version}</span>
        </div>
      </form>
    </Form>
  );
}
