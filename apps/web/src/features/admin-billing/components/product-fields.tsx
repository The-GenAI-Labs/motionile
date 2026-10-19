"use client";

import type { UseFormReturn } from "react-hook-form";

import { Checkbox } from "@/components/ui/checkbox";
import {
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
import {
  IMMUTABILITY_EXPLANATION,
  intervalLabels,
  MAX_FEATURES,
  type ProductFormValues,
} from "@/features/admin-billing/schemas/admin-billing.schema";
import type { ProductKind } from "@/features/admin-billing/types/admin-billing.types";

export function ImmutabilityNotice({ inUse }: { inUse: boolean }) {
  return (
    <div role="note" className="space-y-1 rounded-md border bg-elevated p-3 text-sm">
      {inUse ? <p className="font-medium">This product is in use.</p> : null}
      <p>{IMMUTABILITY_EXPLANATION}</p>
    </div>
  );
}

interface ProductFieldsProps {
  form: UseFormReturn<ProductFormValues>;
  kind: ProductKind;
  mode: "create" | "edit";
  financialLocked: boolean;
}

export function ProductFields({ form, kind, mode, financialLocked }: ProductFieldsProps) {
  const isSubscription = kind === "subscription";
  const lockedHint = financialLocked ? " Locked because the product is in use." : "";
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <FormField
        control={form.control}
        name="code"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Code</FormLabel>
            <FormControl>
              <Input
                autoComplete="off"
                className="font-mono"
                disabled={mode === "edit"}
                {...field}
              />
            </FormControl>
            <FormDescription>
              {mode === "edit"
                ? "The code never changes. Duplicate the product to get a new version code."
                : "Lowercase letters and digits separated by underscores, for example pack_starter."}
            </FormDescription>
            <FormMessage />
          </FormItem>
        )}
      />
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
              <Input
                inputMode="decimal"
                autoComplete="off"
                className="font-mono"
                disabled={financialLocked}
                {...field}
              />
            </FormControl>
            <FormDescription>
              {`Entered in rupees with up to two decimals and stored as paise. Currency is INR.${lockedHint}`}
            </FormDescription>
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
              <Input
                inputMode="numeric"
                autoComplete="off"
                className="font-mono"
                disabled={financialLocked}
                {...field}
              />
            </FormControl>
            <FormDescription>
              {isSubscription
                ? `Credits granted in every billing period.${lockedHint}`
                : `Credits added to the wallet once, and they never expire.${lockedHint}`}
            </FormDescription>
            <FormMessage />
          </FormItem>
        )}
      />
      {isSubscription ? (
        <>
          <FormField
            control={form.control}
            name="interval"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Billing interval</FormLabel>
                <FormControl>
                  <NativeSelect disabled={financialLocked} {...field}>
                    <option value="month">{intervalLabels.month}</option>
                    <option value="year">{intervalLabels.year}</option>
                  </NativeSelect>
                </FormControl>
                <FormDescription>
                  {`Changing it on an unused plan unlinks the Razorpay plan and deactivates the product.${lockedHint}`}
                </FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="planKey"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Plan key</FormLabel>
                <FormControl>
                  <Input
                    autoComplete="off"
                    className="font-mono"
                    disabled={financialLocked}
                    {...field}
                  />
                </FormControl>
                <FormDescription>
                  {`Shared by the monthly and yearly products of one plan. Only one product per plan key and interval can be active.${lockedHint}`}
                </FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
        </>
      ) : null}
      <FormField
        control={form.control}
        name="sortOrder"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Sort order</FormLabel>
            <FormControl>
              <Input inputMode="numeric" autoComplete="off" className="font-mono" {...field} />
            </FormControl>
            <FormDescription>Lower numbers appear first on the pricing page.</FormDescription>
            <FormMessage />
          </FormItem>
        )}
      />
      <FormField
        control={form.control}
        name="description"
        render={({ field }) => (
          <FormItem className="md:col-span-2">
            <FormLabel>Description</FormLabel>
            <FormControl>
              <Textarea rows={2} {...field} />
            </FormControl>
            <FormDescription>
              Shown on the pricing page. A description cannot be cleared once it is set.
            </FormDescription>
            <FormMessage />
          </FormItem>
        )}
      />
      <FormField
        control={form.control}
        name="features"
        render={({ field }) => (
          <FormItem className="md:col-span-2">
            <FormLabel>Features</FormLabel>
            <FormControl>
              <Textarea rows={4} {...field} />
            </FormControl>
            <FormDescription>
              {`One feature per line, at most ${String(MAX_FEATURES)}.`}
            </FormDescription>
            <FormMessage />
          </FormItem>
        )}
      />
      {mode === "create" && !isSubscription ? (
        <FormField
          control={form.control}
          name="isActive"
          render={({ field }) => (
            <FormItem className="md:col-span-2">
              <div className="flex items-start gap-3">
                <FormControl>
                  <Checkbox
                    checked={field.value}
                    onCheckedChange={(checked) => {
                      field.onChange(checked === true);
                    }}
                  />
                </FormControl>
                <div className="grid gap-1">
                  <FormLabel>Make it available to buy straight away</FormLabel>
                  <FormDescription>
                    Leave it off to review the product first and activate it later.
                  </FormDescription>
                </div>
              </div>
            </FormItem>
          )}
        />
      ) : null}
    </div>
  );
}
