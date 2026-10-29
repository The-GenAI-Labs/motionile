"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2Icon, PlusIcon } from "lucide-react";
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
import { Textarea } from "@/components/ui/textarea";
import { adminPromptsErrorMessage } from "@/features/admin-prompts/errors";
import { useCreatePromptDraft } from "@/features/admin-prompts/hooks/use-admin-prompts";
import {
  draftFieldOf,
  draftFormSchema,
  type DraftFormValues,
  emptyDraftValues,
  MAX_BODY_CHARS,
  toDraftInput,
} from "@/features/admin-prompts/schemas/admin-prompts.schema";
import { ApiError } from "@/lib/api/api-error";

interface DraftFormProps {
  templateKey: string;
  onCreated: () => void;
}

function DraftForm({ templateKey, onCreated }: DraftFormProps) {
  const create = useCreatePromptDraft(templateKey);
  const [failure, setFailure] = useState<string | null>(null);
  const form = useForm<DraftFormValues>({
    resolver: zodResolver(draftFormSchema),
    defaultValues: emptyDraftValues,
  });
  const submit = form.handleSubmit(async (values) => {
    setFailure(null);
    try {
      const version = await create.mutateAsync(toDraftInput(values));
      toast.success(`Created draft version ${String(version.version)} of ${templateKey}`);
      onCreated();
    } catch (error) {
      const normalized = ApiError.from(error);
      let placed = false;
      for (const fieldError of normalized.fieldErrors) {
        const field = draftFieldOf(fieldError.field);
        if (field !== undefined) {
          form.setError(field, { message: fieldError.message });
          placed = true;
        }
      }
      setFailure(placed ? null : adminPromptsErrorMessage(error));
    }
  });
  return (
    <Form {...form}>
      <form
        noValidate
        className="grid gap-4"
        onSubmit={(event) => {
          void submit(event);
        }}
      >
        <FormField
          control={form.control}
          name="body"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Prompt text</FormLabel>
              <FormControl>
                <Textarea
                  rows={12}
                  spellCheck={false}
                  autoComplete="off"
                  className="max-h-96 font-mono text-xs"
                  {...field}
                />
              </FormControl>
              <FormDescription>
                {`Jinja template text, up to ${String(MAX_BODY_CHARS)} characters. It is stored as a draft and cannot be read back outside the version diff.`}
              </FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="variables"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Variables (optional)</FormLabel>
              <FormControl>
                <Input autoComplete="off" className="font-mono" {...field} />
              </FormControl>
              <FormDescription>
                Names the template may use, separated by commas or spaces.
              </FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />
        {failure === null ? null : (
          <p role="alert" className="text-sm text-destructive">
            {failure}
          </p>
        )}
        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="outline" disabled={create.isPending}>
              Cancel
            </Button>
          </DialogClose>
          <Button type="submit" disabled={create.isPending} aria-busy={create.isPending}>
            {create.isPending ? (
              <Loader2Icon aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
            ) : null}
            Create draft
          </Button>
        </DialogFooter>
      </form>
    </Form>
  );
}

export function CreateDraftDialog({ templateKey }: { templateKey: string }) {
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline">
          <PlusIcon aria-hidden="true" /> Create draft
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Create a draft of {templateKey}</DialogTitle>
          <DialogDescription>
            A draft never goes live by itself. Run its evaluation suites, then activate it.
          </DialogDescription>
        </DialogHeader>
        {open ? (
          <DraftForm
            templateKey={templateKey}
            onCreated={() => {
              setOpen(false);
            }}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
