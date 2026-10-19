"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2Icon, UndoIcon } from "lucide-react";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";
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
import { Textarea } from "@/components/ui/textarea";
import { adminBillingErrorMessage, hasErrorCode } from "@/features/admin-billing/errors";
import {
  useAdminPayment,
  useClawbackPreview,
  useCreateRefund,
} from "@/features/admin-billing/hooks/use-admin-payments";
import { useIdempotentAttempt } from "@/features/admin-billing/hooks/use-idempotent-attempt";
import {
  MAX_REASON_LENGTH,
  refundFormSchema,
  type RefundFormValues,
} from "@/features/admin-billing/schemas/admin-billing.schema";
import type { AdminPaymentDetail } from "@/features/admin-billing/types/admin-billing.types";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";
import { formatCredits, formatPaise, paiseToDecimalString } from "@/lib/utils/format";
import { parseRupeesToPaise, rupeesToPaise } from "@/lib/utils/money";

const PREVIEW_DEBOUNCE_MS = 300;

interface RefundDialogProps {
  payment: AdminPaymentDetail;
}

interface RefundFormProps extends RefundDialogProps {
  onDone: () => void;
}

const requestedPaise = (amount: string, refundablePaise: number): number | undefined => {
  const paise = parseRupeesToPaise(amount);
  return paise !== null && paise >= 1 && paise <= refundablePaise ? paise : undefined;
};

interface ClawbackPreviewProps {
  credits: number | undefined;
  loading: boolean;
  failed: boolean;
}

function ClawbackPreview({ credits, loading, failed }: ClawbackPreviewProps) {
  let message = "Enter a valid amount to preview the credits that will be clawed back.";
  if (loading) {
    message = "Calculating the credits to claw back.";
  } else if (failed) {
    message = "The clawback preview could not be loaded. The server still applies the same rule.";
  } else if (credits !== undefined) {
    message = `${formatCredits(credits)} ${credits === 1 ? "credit" : "credits"} will be clawed back. Only unused credits of this payment are recovered.`;
  }
  return (
    <p role="status" aria-live="polite" className="rounded-md border bg-elevated p-3 text-sm">
      {message}
    </p>
  );
}

function RefundForm({ payment, onDone }: RefundFormProps) {
  const refundable = payment.refundablePaise;
  const form = useForm<RefundFormValues>({
    resolver: zodResolver(refundFormSchema(refundable)),
    defaultValues: { amount: paiseToDecimalString(refundable), reason: "" },
    mode: "onChange",
  });
  const refund = useCreateRefund(payment.id);
  const attempt = useIdempotentAttempt();
  const latest = useAdminPayment(payment.id);
  const [failure, setFailure] = useState<unknown>(null);
  const amount = useWatch({ control: form.control, name: "amount" });
  const reason = useWatch({ control: form.control, name: "reason" });
  const current = requestedPaise(amount, refundable);
  const requested = useDebouncedValue(current, PREVIEW_DEBOUNCE_MS);
  const needsPreviewRequest = requested !== undefined && requested !== refundable;
  const preview = useClawbackPreview(payment.id, needsPreviewRequest ? requested : undefined);
  const previewCredits = needsPreviewRequest
    ? preview.data?.clawbackPreview.creditsToClawBack
    : requested === undefined
      ? undefined
      : payment.clawbackPreview.creditsToClawBack;

  const submit = form.handleSubmit(async (values) => {
    const request = { amountPaise: rupeesToPaise(values.amount), reason: values.reason };
    setFailure(null);
    try {
      await refund.mutateAsync({
        request,
        idempotencyKey: attempt.keyFor(JSON.stringify(request)),
      });
      attempt.settle();
      toast.success(`Refund of ${formatPaise(request.amountPaise)} requested`);
      onDone();
    } catch (error) {
      attempt.settle(error);
      setFailure(error);
      if (hasErrorCode(error, "refund_exceeds_refundable")) {
        void latest.refetch();
      }
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
        <dl className="grid grid-cols-2 gap-3 text-sm">
          <div>
            <dt className="text-muted-foreground">Payment amount (incl. GST)</dt>
            <dd className="font-mono">{formatPaise(payment.amountPaise)}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Refundable now</dt>
            <dd className="font-mono">{formatPaise(refundable)}</dd>
          </div>
        </dl>
        <FormField
          control={form.control}
          name="amount"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Refund amount (INR)</FormLabel>
              <FormControl>
                <Input inputMode="decimal" autoComplete="off" className="font-mono" {...field} />
              </FormControl>
              <FormDescription>
                Defaults to the full refundable amount. Up to two decimals.
              </FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="reason"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Reason</FormLabel>
              <FormControl>
                <Textarea maxLength={MAX_REASON_LENGTH + 50} rows={3} {...field} />
              </FormControl>
              <FormDescription>
                {reason.trim().length} of {MAX_REASON_LENGTH} characters. Kept in the audit log.
              </FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />
        <ClawbackPreview
          credits={previewCredits}
          loading={current !== requested || (needsPreviewRequest && preview.isFetching)}
          failed={needsPreviewRequest && preview.isError}
        />
        <p className="text-sm text-muted-foreground">
          Refunding does not cancel a subscription. Cancel it separately if needed.
        </p>
        {failure === null ? null : (
          <p role="alert" className="text-sm text-destructive">
            {adminBillingErrorMessage(failure)}
          </p>
        )}
        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="outline" disabled={refund.isPending}>
              Cancel
            </Button>
          </DialogClose>
          <Button
            type="submit"
            variant="destructive"
            disabled={!form.formState.isValid || refund.isPending}
            aria-busy={refund.isPending}
          >
            {refund.isPending ? (
              <Loader2Icon aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
            ) : null}
            Refund payment
          </Button>
        </DialogFooter>
      </form>
    </Form>
  );
}

export function RefundDialog({ payment }: RefundDialogProps) {
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline">
          <UndoIcon aria-hidden="true" /> Refund
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Refund payment</DialogTitle>
          <DialogDescription>
            The money goes back to the customer through Razorpay. This cannot be undone.
          </DialogDescription>
        </DialogHeader>
        {open ? (
          <RefundForm
            payment={payment}
            onDone={() => {
              setOpen(false);
            }}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
