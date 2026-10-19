"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2Icon, SlidersHorizontalIcon } from "lucide-react";
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
import { adminBillingErrorMessage } from "@/features/admin-billing/errors";
import { useAdjustCredits } from "@/features/admin-billing/hooks/use-admin-user-credits";
import { useIdempotentAttempt } from "@/features/admin-billing/hooks/use-idempotent-attempt";
import {
  adjustFormSchema,
  type AdjustFormValues,
  MAX_REASON_LENGTH,
  toAdjustRequest,
} from "@/features/admin-billing/schemas/admin-billing.schema";
import { formatCredits } from "@/lib/utils/format";

interface AdjustFormProps {
  userId: string;
  availableCredits: number;
  onDone: () => void;
}

function AdjustForm({ userId, availableCredits, onDone }: AdjustFormProps) {
  const form = useForm<AdjustFormValues>({
    resolver: zodResolver(adjustFormSchema),
    defaultValues: { delta: "", reason: "", expiresAt: "" },
    mode: "onChange",
  });
  const adjust = useAdjustCredits(userId);
  const attempt = useIdempotentAttempt();
  const [failure, setFailure] = useState<unknown>(null);
  const reason = useWatch({ control: form.control, name: "reason" });

  const submit = form.handleSubmit(async (values) => {
    const request = toAdjustRequest(values);
    setFailure(null);
    try {
      const result = await adjust.mutateAsync({
        request,
        idempotencyKey: attempt.keyFor(JSON.stringify(request)),
      });
      attempt.settle();
      toast.success(`Balance is now ${formatCredits(result.balanceAfter)} credits`);
      onDone();
    } catch (error) {
      attempt.settle(error);
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
        <p className="text-sm text-muted-foreground">
          {formatCredits(availableCredits)} credits are available to remove right now. Reserved
          credits cannot be removed.
        </p>
        <FormField
          control={form.control}
          name="delta"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Credits to add or remove</FormLabel>
              <FormControl>
                <Input inputMode="numeric" autoComplete="off" className="font-mono" {...field} />
              </FormControl>
              <FormDescription>
                A positive number grants credits, a negative number removes them. For example 50 or
                -20.
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
                <Textarea rows={3} {...field} />
              </FormControl>
              <FormDescription>
                {reason.trim().length} of {MAX_REASON_LENGTH} characters. Kept in the audit log.
              </FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="expiresAt"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Expiry (optional)</FormLabel>
              <FormControl>
                <Input type="datetime-local" {...field} />
              </FormControl>
              <FormDescription>
                Only for grants. Leave empty so the credits never expire.
              </FormDescription>
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
            <Button type="button" variant="outline" disabled={adjust.isPending}>
              Cancel
            </Button>
          </DialogClose>
          <Button
            type="submit"
            disabled={!form.formState.isValid || adjust.isPending}
            aria-busy={adjust.isPending}
          >
            {adjust.isPending ? (
              <Loader2Icon aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
            ) : null}
            Apply adjustment
          </Button>
        </DialogFooter>
      </form>
    </Form>
  );
}

interface AdjustCreditsDialogProps {
  userId: string;
  availableCredits: number;
}

export function AdjustCreditsDialog({ userId, availableCredits }: AdjustCreditsDialogProps) {
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline">
          <SlidersHorizontalIcon aria-hidden="true" /> Adjust credits
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Adjust credits</DialogTitle>
          <DialogDescription>
            Writes a permanent ledger entry with your reason. Mistakes are corrected with another
            adjustment, never by editing a row.
          </DialogDescription>
        </DialogHeader>
        {open ? (
          <AdjustForm
            userId={userId}
            availableCredits={availableCredits}
            onDone={() => {
              setOpen(false);
            }}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
