"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2Icon } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { usePublicSettings } from "@/features/platform/hooks/use-flags";
import { voiceErrorMessage } from "@/features/voices/errors";
import { useStartClone } from "@/features/voices/hooks/use-clone-attempt";
import { useCloneWizardStore } from "@/features/voices/store/clone-wizard.store";
import { ApiError } from "@/lib/api/api-error";

const STATEMENT_KEY = "voices.consent_statement";
const VERSION_KEY = "voices.consent_statement_version";

const consentFormSchema = z.object({
  accepted: z.boolean().refine((value) => value, {
    message: "Accept the statement to continue.",
  }),
});

type ConsentFormValues = z.infer<typeof consentFormSchema>;

const textSetting = (value: unknown): string | null =>
  typeof value === "string" && value !== "" ? value : null;

export function ConsentStep() {
  const settings = usePublicSettings();
  const startClone = useStartClone();
  const setStart = useCloneWizardStore((state) => state.setStart);
  const [failure, setFailure] = useState<unknown>(null);
  const form = useForm<ConsentFormValues>({
    resolver: zodResolver(consentFormSchema),
    defaultValues: { accepted: false },
  });
  const statement = textSetting(settings.data?.settings[STATEMENT_KEY]);
  const version = textSetting(settings.data?.settings[VERSION_KEY]);

  const submit = form.handleSubmit(async () => {
    if (version === null) {
      return;
    }
    setFailure(null);
    try {
      setStart(await startClone.mutateAsync(version));
    } catch (error) {
      setFailure(error);
      if (ApiError.from(error).code === "consent_statement_outdated") {
        form.reset({ accepted: false });
        void settings.refetch();
      }
    }
  });

  if (settings.isPending) {
    return (
      <p role="status" className="text-sm text-muted-foreground">
        Loading the consent statement
      </p>
    );
  }
  if (statement === null || version === null) {
    return (
      <div role="alert" className="flex flex-wrap items-center gap-3 text-sm text-destructive">
        <p>The consent statement could not be loaded.</p>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            void settings.refetch();
          }}
        >
          Try again
        </Button>
      </div>
    );
  }
  return (
    <Form {...form}>
      <form
        noValidate
        className="space-y-6"
        onSubmit={(event) => {
          void submit(event);
        }}
      >
        <section aria-labelledby="consent-statement-heading" className="space-y-3">
          <h3 id="consent-statement-heading" className="text-lg font-medium">
            Consent statement
          </h3>
          <p className="font-mono text-xs text-muted-foreground">{`Version ${version}`}</p>
          <blockquote className="max-h-72 overflow-y-auto rounded-lg border bg-surface p-4 text-sm leading-relaxed whitespace-pre-line">
            {statement}
          </blockquote>
        </section>
        <FormField
          control={form.control}
          name="accepted"
          render={({ field }) => (
            <FormItem>
              <div className="flex items-start gap-3">
                <FormControl>
                  <Checkbox
                    checked={field.value}
                    onCheckedChange={(checked) => {
                      field.onChange(checked === true);
                    }}
                  />
                </FormControl>
                <FormLabel>
                  I have read and accept this statement. The voice I clone is my own.
                </FormLabel>
              </div>
              <FormMessage />
            </FormItem>
          )}
        />
        {failure === null ? null : (
          <p role="alert" className="text-sm text-destructive">
            {voiceErrorMessage(failure)}
          </p>
        )}
        <Button type="submit" disabled={startClone.isPending} aria-busy={startClone.isPending}>
          {startClone.isPending ? (
            <Loader2Icon aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
          ) : null}
          Accept and continue
        </Button>
      </form>
    </Form>
  );
}
