"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2Icon, RefreshCwIcon } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";

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
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { generationErrorMessage } from "@/features/generation/errors";
import { useRegenerateStoryboard } from "@/features/generation/hooks/use-storyboard";
import {
  INSTRUCTIONS_MAX_CHARS,
  regenerateFormSchema,
  type RegenerateFormValues,
} from "@/features/generation/schemas/generation.schema";

export function RegenerateDialog({ jobId, disabled }: { jobId: string; disabled: boolean }) {
  const [open, setOpen] = useState(false);
  const regenerate = useRegenerateStoryboard(jobId);
  const form = useForm<RegenerateFormValues>({
    resolver: zodResolver(regenerateFormSchema),
    defaultValues: { instructions: "" },
  });
  const submit = form.handleSubmit(async (values) => {
    try {
      await regenerate.mutateAsync(values.instructions);
      setOpen(false);
      form.reset();
    } catch {
      return;
    }
  });
  const error = form.formState.errors.instructions?.message;
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) {
          regenerate.reset();
        }
      }}
    >
      <DialogTrigger asChild>
        <Button type="button" variant="outline" disabled={disabled}>
          <RefreshCwIcon aria-hidden="true" /> Regenerate with instructions
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Regenerate the storyboard</DialogTitle>
          <DialogDescription>
            Tell Motionile what to change. It plans a new storyboard and your current edits are
            replaced.
          </DialogDescription>
        </DialogHeader>
        <form
          noValidate
          className="grid gap-4"
          onSubmit={(event) => {
            void submit(event);
          }}
        >
          <div className="space-y-2">
            <Label htmlFor="regenerate-instructions">Instructions</Label>
            <Textarea
              id="regenerate-instructions"
              rows={5}
              maxLength={INSTRUCTIONS_MAX_CHARS}
              aria-invalid={error !== undefined}
              aria-describedby={error ? "regenerate-error" : undefined}
              {...form.register("instructions")}
            />
            {error ? (
              <p id="regenerate-error" role="alert" className="text-sm text-destructive">
                {error}
              </p>
            ) : null}
          </div>
          {regenerate.error ? (
            <p role="alert" className="text-sm text-destructive">
              {generationErrorMessage(regenerate.error)}
            </p>
          ) : null}
          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="outline" disabled={regenerate.isPending}>
                Cancel
              </Button>
            </DialogClose>
            <Button type="submit" disabled={regenerate.isPending} aria-busy={regenerate.isPending}>
              {regenerate.isPending ? (
                <Loader2Icon
                  aria-hidden="true"
                  className="animate-spin motion-reduce:animate-none"
                />
              ) : null}
              Regenerate
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
