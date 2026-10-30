"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2Icon } from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Controller, useForm, useWatch } from "react-hook-form";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { AspectField } from "@/features/generation/components/aspect-field";
import { CreateOptions } from "@/features/generation/components/create-options";
import { DurationField } from "@/features/generation/components/duration-field";
import { EstimatePanel } from "@/features/generation/components/estimate-panel";
import { StylePicker } from "@/features/generation/components/style-picker";
import { type SelectedTopic, TopicField } from "@/features/generation/components/topic-field";
import { VoiceField } from "@/features/generation/components/voice-field";
import { generationErrorMessage } from "@/features/generation/errors";
import { useCreateJob } from "@/features/generation/hooks/use-create-job";
import { useJobEstimate } from "@/features/generation/hooks/use-job-estimate";
import { useStyles } from "@/features/generation/hooks/use-styles";
import { useTopicReference } from "@/features/generation/hooks/use-topic-reference";
import {
  ALL_ASPECTS,
  createJobFormSchema,
  type CreateJobFormValues,
  DEFAULT_DURATION_SECONDS,
  DEFAULT_STYLE_SLUG,
  DURATION_MAX_SECONDS,
  DURATION_MIN_SECONDS,
  DURATION_STEP_SECONDS,
} from "@/features/generation/schemas/generation.schema";
import type { Aspect, StyleOption } from "@/features/generation/types/generation.types";
import { usePublicSettings } from "@/features/platform/hooks/use-flags";
import { useUserPreferences } from "@/features/users/hooks/use-user-settings";

const stringList = (value: unknown, fallback: readonly string[]): readonly string[] =>
  Array.isArray(value) && value.length > 0 && value.every((item) => typeof item === "string")
    ? value
    : fallback;

const clampDuration = (seconds: number): number => {
  const stepped = Math.round(seconds / DURATION_STEP_SECONDS) * DURATION_STEP_SECONDS;
  return Math.min(DURATION_MAX_SECONDS, Math.max(DURATION_MIN_SECONDS, stepped));
};

const pickStyle = (
  styles: readonly StyleOption[],
  preferred: string | null | undefined,
): string => {
  const slugs = styles.map((style) => style.slug);
  if (preferred !== undefined && preferred !== null && slugs.includes(preferred)) {
    return preferred;
  }
  return slugs.includes(DEFAULT_STYLE_SLUG) ? DEFAULT_STYLE_SLUG : (slugs[0] ?? DEFAULT_STYLE_SLUG);
};

interface FormBodyProps {
  defaults: CreateJobFormValues;
  languages: readonly string[];
  aspects: readonly Aspect[];
  notice: string | null;
}

function CreateVideoFormBody({ defaults, languages, aspects, notice }: FormBodyProps) {
  const router = useRouter();
  const styles = useStyles();
  const create = useCreateJob();
  const [topic, setTopic] = useState<SelectedTopic | null>(
    defaults.topicId === null
      ? null
      : { id: defaults.topicId, title: defaults.topicTitle, suggestedDurationSeconds: null },
  );
  const form = useForm<CreateJobFormValues>({
    resolver: zodResolver(createJobFormSchema),
    defaultValues: defaults,
  });
  const { control, formState, setValue } = form;
  const [query, durationSeconds, selectedAspects, voiceId] = useWatch({
    control,
    name: ["query", "durationSeconds", "aspects", "voiceId"],
  });
  const estimate = useJobEstimate({ durationSeconds, aspects: selectedAspects, voiceId });
  const unaffordable = estimate.estimate?.affordable === false;

  const selectTopic = (next: SelectedTopic) => {
    setTopic(next);
    setValue("topicId", next.id, { shouldValidate: true });
    setValue("topicTitle", next.title);
    if (next.suggestedDurationSeconds !== null) {
      setValue("durationSeconds", clampDuration(next.suggestedDurationSeconds));
    }
  };
  const clearTopic = () => {
    setTopic(null);
    setValue("topicId", null);
    setValue("topicTitle", null);
  };

  const onSubmit = form.handleSubmit(async (values) => {
    const job = await create.submit(values);
    if (job !== null) {
      router.push(`/jobs/${job.id}` as Route);
    }
  });

  return (
    <form
      noValidate
      aria-label="Create a video"
      className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_20rem]"
      onSubmit={(event) => {
        void onSubmit(event);
      }}
    >
      <div className="space-y-8">
        <TopicField
          query={query}
          onQueryChange={(next) => {
            setValue("query", next, { shouldValidate: formState.isSubmitted });
          }}
          topic={topic}
          onSelect={selectTopic}
          onClear={clearTopic}
          notice={notice}
          error={formState.errors.query?.message}
        />
        <Controller
          control={control}
          name="durationSeconds"
          render={({ field }) => <DurationField value={field.value} onChange={field.onChange} />}
        />
        <Controller
          control={control}
          name="aspects"
          render={({ field }) => (
            <AspectField
              value={field.value}
              allowed={aspects}
              onChange={field.onChange}
              error={formState.errors.aspects?.message}
            />
          )}
        />
        <Controller
          control={control}
          name="style"
          render={({ field }) => (
            <StylePicker
              styles={styles.data}
              isLoading={styles.isPending}
              isError={styles.isError}
              value={field.value}
              onChange={field.onChange}
              error={formState.errors.style?.message}
            />
          )}
        />
        <Controller
          control={control}
          name="voiceId"
          render={({ field }) => (
            <VoiceField
              value={field.value}
              onChange={field.onChange}
              clonedPremium={estimate.estimate?.parameters.clonedVoicePremium ?? null}
            />
          )}
        />
        <CreateOptions form={form} languages={languages} />
      </div>
      <aside className="space-y-4 lg:sticky lg:top-6 lg:self-start">
        <EstimatePanel estimate={estimate} />
        {create.error ? (
          <p role="alert" className="text-sm text-destructive">
            {generationErrorMessage(create.error)}
          </p>
        ) : null}
        {unaffordable ? (
          <Button asChild className="w-full">
            <Link href="/billing/credits">Buy credits to continue</Link>
          </Button>
        ) : (
          <Button
            type="submit"
            className="w-full"
            disabled={create.isSubmitting}
            aria-busy={create.isSubmitting}
          >
            {create.isSubmitting ? (
              <Loader2Icon aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
            ) : null}
            Create video
          </Button>
        )}
      </aside>
    </form>
  );
}

interface CreateVideoFormProps {
  topicReference: string | null;
  initialQuery: string;
}

export function CreateVideoForm({ topicReference, initialQuery }: CreateVideoFormProps) {
  const preferences = useUserPreferences();
  const settings = usePublicSettings();
  const styles = useStyles();
  const topic = useTopicReference(topicReference);
  const loading =
    preferences.isPending ||
    settings.isPending ||
    styles.isPending ||
    (topicReference !== null && topic.isPending);
  if (loading) {
    return (
      <div role="status" aria-label="Loading the form" className="space-y-4">
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }
  const values = settings.data?.settings ?? {};
  const languages = stringList(values["preferences.languages"], ["en"]);
  const allowedAspects = stringList(values["preferences.aspects"], ALL_ASPECTS).filter(
    (item): item is Aspect => (ALL_ASPECTS as readonly string[]).includes(item),
  );
  const aspects = allowedAspects.length > 0 ? allowedAspects : [...ALL_ASPECTS];
  const preferredLanguage = preferences.data?.language;
  const preferredAspect = preferences.data?.defaultAspect;
  const resolved = topic.data ?? null;
  const suggested = resolved?.suggestedDurationSeconds ?? null;
  const defaults: CreateJobFormValues = {
    topicId: resolved?.id ?? null,
    topicTitle: resolved?.title ?? null,
    query: initialQuery,
    durationSeconds: suggested === null ? DEFAULT_DURATION_SECONDS : clampDuration(suggested),
    aspects: [aspects.find((item) => item === preferredAspect) ?? aspects[0] ?? "16:9"],
    style: pickStyle(styles.data ?? [], preferences.data?.defaultStyle),
    voiceId: null,
    language:
      preferredLanguage !== undefined && languages.includes(preferredLanguage)
        ? preferredLanguage
        : (languages[0] ?? "en"),
    reviewStoryboard: false,
    subtitles: preferences.data?.captionsEnabled ?? true,
    burnInSubtitles: false,
  };
  const notice =
    topicReference !== null && topic.isSuccess && resolved === null
      ? "That topic could not be found. Describe what you want explained instead."
      : null;
  return (
    <CreateVideoFormBody
      defaults={defaults}
      languages={languages}
      aspects={aspects}
      notice={notice}
    />
  );
}
