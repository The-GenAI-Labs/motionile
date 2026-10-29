"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2Icon, PencilIcon } from "lucide-react";
import type { Route } from "next";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Controller, useForm, useWatch } from "react-hook-form";

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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { generationErrorMessage } from "@/features/generation/errors";
import { useReviseJob } from "@/features/generation/hooks/use-job-actions";
import { useStoryboard } from "@/features/generation/hooks/use-storyboard";
import { useStyles } from "@/features/generation/hooks/use-styles";
import {
  DURATION_MAX_SECONDS,
  DURATION_MIN_SECONDS,
  INSTRUCTIONS_MAX_CHARS,
  reviseFormSchema,
  type ReviseFormValues,
} from "@/features/generation/schemas/generation.schema";
import type { Job } from "@/features/generation/types/generation.types";

const buildBody = (values: ReviseFormValues) => ({
  instructions: values.instructions,
  ...(values.sceneIds.length > 0 ? { sceneIds: values.sceneIds } : {}),
  ...(values.overrideDuration || values.overrideStyle
    ? {
        options: {
          ...(values.overrideDuration ? { durationSeconds: values.durationSeconds } : {}),
          ...(values.overrideStyle ? { style: values.style } : {}),
        },
      }
    : {}),
});

function ReviseForm({ job, onDone }: { job: Job; onDone: () => void }) {
  const router = useRouter();
  const revise = useReviseJob(job.id);
  const storyboard = useStoryboard(job.id, true);
  const styles = useStyles();
  const form = useForm<ReviseFormValues>({
    resolver: zodResolver(reviseFormSchema),
    defaultValues: {
      instructions: "",
      sceneIds: [],
      overrideDuration: false,
      durationSeconds: job.options.durationSeconds,
      overrideStyle: false,
      style: job.options.style,
    },
  });
  const { control, formState, register } = form;
  const [overrideDuration, overrideStyle] = useWatch({
    control,
    name: ["overrideDuration", "overrideStyle"],
  });
  const submit = form.handleSubmit(async (values) => {
    const created = await revise.submit(buildBody(values));
    if (created !== null) {
      onDone();
      router.push(`/jobs/${created.id}` as Route);
    }
  });
  const scenes = storyboard.data?.content.scenes ?? [];
  const instructionsError = formState.errors.instructions?.message;
  return (
    <form
      noValidate
      className="grid gap-5"
      onSubmit={(event) => {
        void submit(event);
      }}
    >
      <div className="space-y-2">
        <Label htmlFor="revise-instructions">What should change?</Label>
        <Textarea
          id="revise-instructions"
          rows={4}
          maxLength={INSTRUCTIONS_MAX_CHARS}
          aria-invalid={instructionsError !== undefined}
          aria-describedby={instructionsError ? "revise-instructions-error" : undefined}
          {...register("instructions")}
        />
        {instructionsError ? (
          <p id="revise-instructions-error" role="alert" className="text-sm text-destructive">
            {instructionsError}
          </p>
        ) : null}
      </div>
      {scenes.length > 0 ? (
        <Controller
          control={control}
          name="sceneIds"
          render={({ field }) => (
            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">Only change these scenes (optional)</legend>
              <ul className="space-y-1">
                {scenes.map((scene, index) => (
                  <li key={scene.id} className="flex items-start gap-2 text-sm">
                    <input
                      id={`revise-scene-${scene.id}`}
                      type="checkbox"
                      checked={field.value.includes(scene.id)}
                      className="mt-1 size-4 accent-primary"
                      onChange={(event) => {
                        field.onChange(
                          event.target.checked
                            ? [...field.value, scene.id]
                            : field.value.filter((id) => id !== scene.id),
                        );
                      }}
                    />
                    <Label htmlFor={`revise-scene-${scene.id}`} className="font-normal">
                      {`Scene ${String(index + 1)}: ${scene.goal}`}
                    </Label>
                  </li>
                ))}
              </ul>
            </fieldset>
          )}
        />
      ) : null}
      <div className="space-y-3">
        <Controller
          control={control}
          name="overrideDuration"
          render={({ field }) => (
            <div className="flex items-center gap-3">
              <Switch
                id="revise-override-duration"
                checked={field.value}
                onCheckedChange={field.onChange}
              />
              <Label htmlFor="revise-override-duration">Change the length</Label>
            </div>
          )}
        />
        {overrideDuration ? (
          <div className="space-y-2">
            <Label htmlFor="revise-duration">New length in seconds</Label>
            <Input
              id="revise-duration"
              type="number"
              min={DURATION_MIN_SECONDS}
              max={DURATION_MAX_SECONDS}
              step={1}
              {...register("durationSeconds", { valueAsNumber: true })}
            />
          </div>
        ) : null}
        <Controller
          control={control}
          name="overrideStyle"
          render={({ field }) => (
            <div className="flex items-center gap-3">
              <Switch
                id="revise-override-style"
                checked={field.value}
                onCheckedChange={field.onChange}
              />
              <Label htmlFor="revise-override-style">Change the style</Label>
            </div>
          )}
        />
        {overrideStyle ? (
          <div className="space-y-2">
            <Label htmlFor="revise-style">New style</Label>
            <NativeSelect id="revise-style" {...register("style")}>
              {(styles.data ?? []).map((style) => (
                <option key={style.slug} value={style.slug}>
                  {style.name}
                </option>
              ))}
            </NativeSelect>
          </div>
        ) : null}
      </div>
      {revise.error ? (
        <p role="alert" className="text-sm text-destructive">
          {generationErrorMessage(revise.error)}
        </p>
      ) : null}
      <DialogFooter>
        <DialogClose asChild>
          <Button type="button" variant="outline" disabled={revise.isSubmitting}>
            Cancel
          </Button>
        </DialogClose>
        <Button type="submit" disabled={revise.isSubmitting} aria-busy={revise.isSubmitting}>
          {revise.isSubmitting ? (
            <Loader2Icon aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
          ) : null}
          Start revision
        </Button>
      </DialogFooter>
    </form>
  );
}

export function ReviseDialog({ job }: { job: Job }) {
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button type="button" variant="outline">
          <PencilIcon aria-hidden="true" /> Revise
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Revise this video</DialogTitle>
          <DialogDescription>
            Describe what to change. Motionile makes a new video and keeps this one. A revision uses
            credits like any other video.
          </DialogDescription>
        </DialogHeader>
        {open ? (
          <ReviseForm
            job={job}
            onDone={() => {
              setOpen(false);
            }}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
