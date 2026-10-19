"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { CopyIcon, Loader2Icon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Textarea } from "@/components/ui/textarea";
import { adminBillingErrorMessage } from "@/features/admin-billing/errors";
import { useDuplicateProduct } from "@/features/admin-billing/hooks/use-admin-products";
import { adminBillingPaths } from "@/features/admin-billing/paths";
import {
  duplicateFormSchema,
  type DuplicateFormValues,
  duplicateFormValues,
  intervalLabels,
  toDuplicateRequest,
} from "@/features/admin-billing/schemas/admin-billing.schema";
import type { AdminProductDetail } from "@/features/admin-billing/types/admin-billing.types";

interface DuplicateFormProps {
  product: AdminProductDetail;
}

function DuplicateForm({ product }: DuplicateFormProps) {
  const router = useRouter();
  const duplicate = useDuplicateProduct(product.id);
  const [failure, setFailure] = useState<unknown>(null);
  const form = useForm<DuplicateFormValues>({
    resolver: zodResolver(duplicateFormSchema),
    defaultValues: duplicateFormValues(product),
  });
  const submit = form.handleSubmit(async (values) => {
    setFailure(null);
    try {
      const created = await duplicate.mutateAsync(toDuplicateRequest(values, product));
      toast.success(`Created ${created.code}`);
      router.push(adminBillingPaths.product(created.id));
    } catch (error) {
      setFailure(error);
    }
  });
  return (
    <Form {...form}>
      <form
        className="grid gap-4"
        onSubmit={(event) => {
          void submit(event);
        }}
      >
        <FormField
          control={form.control}
          name="name"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Name</FormLabel>
              <FormControl>
                <Input autoComplete="off" {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="price"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Price in rupees (incl. GST)</FormLabel>
              <FormControl>
                <Input inputMode="decimal" autoComplete="off" className="font-mono" {...field} />
              </FormControl>
              <FormDescription>Up to two decimals. Stored as paise.</FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="creditsGranted"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Credits granted</FormLabel>
              <FormControl>
                <Input inputMode="numeric" autoComplete="off" className="font-mono" {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        {product.kind === "subscription" ? (
          <FormField
            control={form.control}
            name="interval"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Billing interval</FormLabel>
                <FormControl>
                  <NativeSelect {...field}>
                    <option value="month">{intervalLabels.month}</option>
                    <option value="year">{intervalLabels.year}</option>
                  </NativeSelect>
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        ) : null}
        <FormField
          control={form.control}
          name="description"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Description</FormLabel>
              <FormControl>
                <Textarea rows={2} {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        {failure === null ? null : (
          <p role="alert" className="text-sm text-destructive">
            {adminBillingErrorMessage(failure)}
          </p>
        )}
        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="outline" disabled={duplicate.isPending}>
              Cancel
            </Button>
          </DialogClose>
          <Button type="submit" disabled={duplicate.isPending} aria-busy={duplicate.isPending}>
            {duplicate.isPending ? (
              <Loader2Icon aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
            ) : null}
            Create new version
          </Button>
        </DialogFooter>
      </form>
    </Form>
  );
}

export function DuplicateProductDialog({ product }: DuplicateFormProps) {
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline">
          <CopyIcon aria-hidden="true" /> Duplicate as new version
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Duplicate as new version</DialogTitle>
          <DialogDescription>
            Creates an inactive copy as version {product.version + 1}, which supersedes this
            product. Existing subscribers stay on their current plan until they change it.
            {product.kind === "subscription"
              ? " Sync the Razorpay plan of the copy, activate it, then deactivate this product."
              : " Activate the copy, then deactivate this product."}
          </DialogDescription>
        </DialogHeader>
        {open ? <DuplicateForm product={product} /> : null}
      </DialogContent>
    </Dialog>
  );
}
