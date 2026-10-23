"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2Icon } from "lucide-react";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/button";
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
import { voiceErrorMessage } from "@/features/voices/errors";
import { useCloneSubmit } from "@/features/voices/hooks/use-clone-submit";
import {
  cloneSubmitFormSchema,
  type CloneSubmitFormValues,
  MAX_VOICE_NAME_LENGTH,
  voiceLanguageOptions,
} from "@/features/voices/schemas/voices.schema";
import { useCloneWizardStore } from "@/features/voices/store/clone-wizard.store";
import type { CloneStart } from "@/features/voices/types/voices.types";

interface DetailsStepProps {
  start: CloneStart;
}

export function DetailsStep({ start }: DetailsStepProps) {
  const setStep = useCloneWizardStore((state) => state.setStep);
  const setSubmittedVoiceId = useCloneWizardStore((state) => state.setSubmittedVoiceId);
  const clone = useCloneSubmit(start.attemptId);
  const form = useForm<CloneSubmitFormValues>({
    resolver: zodResolver(cloneSubmitFormSchema),
    defaultValues: { name: "", language: "en" },
  });

  const submit = form.handleSubmit(async (values) => {
    const voice = await clone.submit(values);
    if (voice !== null) {
      setSubmittedVoiceId(voice.id);
    }
  });

  return (
    <Form {...form}>
      <form
        noValidate
        className="space-y-6"
        onSubmit={(event) => {
          void submit(event);
        }}
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField
            control={form.control}
            name="name"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Voice name</FormLabel>
                <FormControl>
                  <Input autoComplete="off" maxLength={MAX_VOICE_NAME_LENGTH} {...field} />
                </FormControl>
                <FormDescription>
                  Shown in your voice list and when you pick a voice.
                </FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="language"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Language you speak</FormLabel>
                <FormControl>
                  <NativeSelect {...field}>
                    {voiceLanguageOptions.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </NativeSelect>
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        </div>
        {clone.error === null ? null : (
          <p role="alert" className="text-sm text-destructive">
            {voiceErrorMessage(clone.error)}
          </p>
        )}
        <div className="flex flex-wrap gap-3">
          <Button
            type="button"
            variant="outline"
            disabled={clone.isPending}
            onClick={() => {
              setStep("samples");
            }}
          >
            Back
          </Button>
          <Button type="submit" disabled={clone.isPending} aria-busy={clone.isPending}>
            {clone.isPending ? (
              <Loader2Icon aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
            ) : null}
            Create my voice
          </Button>
        </div>
      </form>
    </Form>
  );
}
