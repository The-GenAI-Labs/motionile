"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { FlaskConicalIcon, Loader2Icon } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { NativeSelect } from "@/components/ui/native-select";
import { adminPromptsErrorMessage } from "@/features/admin-prompts/errors";
import { useStartEvalRun } from "@/features/admin-prompts/hooks/use-admin-prompts";
import {
  EVAL_SUITES,
  startEvalFormSchema,
  type StartEvalFormValues,
} from "@/features/admin-prompts/schemas/admin-prompts.schema";
import type { PromptVersion } from "@/features/admin-prompts/types/admin-prompts.types";

interface StartEvalFormProps {
  versions: readonly PromptVersion[];
  onStarted: () => void;
}

function StartEvalForm({ versions, onStarted }: StartEvalFormProps) {
  const start = useStartEvalRun();
  const [failure, setFailure] = useState<unknown>(null);
  const form = useForm<StartEvalFormValues>({
    resolver: zodResolver(startEvalFormSchema),
    defaultValues: { suite: "", versionIds: [] },
  });
  const submit = form.handleSubmit(async (values) => {
    setFailure(null);
    try {
      const run = await start.mutateAsync({ suite: values.suite, versionIds: values.versionIds });
      toast.success(`Started the ${run.suite} suite`);
      onStarted();
    } catch (error) {
      setFailure(error);
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
          name="suite"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Suite</FormLabel>
              <FormControl>
                <NativeSelect {...field}>
                  <option value="">Choose a suite</option>
                  {EVAL_SUITES.map((suite) => (
                    <option key={suite} value={suite}>
                      {suite}
                    </option>
                  ))}
                </NativeSelect>
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="versionIds"
          render={({ field }) => (
            <FormItem>
              <fieldset className="space-y-2">
                <legend className="text-sm font-medium text-subtle-foreground">Versions</legend>
                {versions.map((version) => {
                  const id = `eval-version-${version.id}`;
                  return (
                    <div key={version.id} className="flex items-center gap-2">
                      <Checkbox
                        id={id}
                        checked={field.value.includes(version.id)}
                        onCheckedChange={(checked) => {
                          field.onChange(
                            checked === true
                              ? [...field.value, version.id]
                              : field.value.filter((value) => value !== version.id),
                          );
                        }}
                      />
                      <label htmlFor={id} className="text-sm">
                        Version {version.version}
                        {version.isActive ? " (active)" : ""}
                      </label>
                    </div>
                  );
                })}
              </fieldset>
              <FormMessage />
            </FormItem>
          )}
        />
        {failure === null ? null : (
          <p role="alert" className="text-sm text-destructive">
            {adminPromptsErrorMessage(failure)}
          </p>
        )}
        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="outline" disabled={start.isPending}>
              Cancel
            </Button>
          </DialogClose>
          <Button type="submit" disabled={start.isPending} aria-busy={start.isPending}>
            {start.isPending ? (
              <Loader2Icon aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
            ) : null}
            Start run
          </Button>
        </DialogFooter>
      </form>
    </Form>
  );
}

export function StartEvalDialog({ versions }: { versions: readonly PromptVersion[] }) {
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <FlaskConicalIcon aria-hidden="true" /> Start eval run
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Start an evaluation run</DialogTitle>
          <DialogDescription>
            The run scores the selected versions against one suite. It finishes in the background.
          </DialogDescription>
        </DialogHeader>
        {open ? (
          <StartEvalForm
            versions={versions}
            onStarted={() => {
              setOpen(false);
            }}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
