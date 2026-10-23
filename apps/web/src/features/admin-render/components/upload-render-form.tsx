"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2Icon, UploadIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useFieldArray, useForm, useWatch } from "react-hook-form";

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
import { NarrationFields } from "@/features/admin-render/components/narration-fields";
import { RenderChoicesFields } from "@/features/admin-render/components/render-choices-fields";
import { adminRenderErrorMessage } from "@/features/admin-render/errors";
import { useCreateTestbedRender } from "@/features/admin-render/hooks/use-testbed";
import { extractScenes } from "@/features/admin-render/scene-ids";
import {
  compositionFileError,
  emptyRenderFormValues,
  renderFormSchema,
  type RenderFormValues,
} from "@/features/admin-render/schemas/admin-render.schema";

export function UploadRenderForm() {
  const router = useRouter();
  const create = useCreateTestbedRender();
  const [failure, setFailure] = useState<unknown>(null);
  const [sceneIssues, setSceneIssues] = useState<string[]>([]);
  const form = useForm<RenderFormValues>({
    resolver: zodResolver(renderFormSchema),
    defaultValues: emptyRenderFormValues(),
  });
  const scenes = useFieldArray({ control: form.control, name: "scenes", keyName: "key" });
  const mode = useWatch({ control: form.control, name: "mode" });

  const chooseComposition = async (file: File | undefined): Promise<void> => {
    form.setValue("composition", file);
    setSceneIssues([]);
    const problem = file === undefined ? null : compositionFileError(file);
    if (file === undefined || problem !== null) {
      scenes.replace([]);
      if (problem !== null) {
        form.setError("composition", { type: "custom", message: problem });
      }
      return;
    }
    form.clearErrors("composition");
    const extraction = extractScenes(await file.text());
    const existing = form.getValues("scenes");
    scenes.replace(
      extraction.sceneIds.map(
        (sceneId) => existing.find((scene) => scene.sceneId === sceneId) ?? { sceneId, text: "" },
      ),
    );
    setSceneIssues(extraction.issues);
  };

  const submit = form.handleSubmit(async (values) => {
    setFailure(null);
    try {
      const render = await create.mutateAsync(values);
      router.push(`/admin/render/${render.id}`);
    } catch (error) {
      setFailure(error);
    }
  });

  return (
    <Form {...form}>
      <form
        noValidate
        aria-label="Render a composition"
        className="space-y-8"
        onSubmit={(event) => {
          void submit(event);
        }}
      >
        <FormField
          control={form.control}
          name="composition"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Composition HTML file</FormLabel>
              <FormControl>
                <Input
                  type="file"
                  accept=".html,text/html"
                  name={field.name}
                  ref={field.ref}
                  onBlur={field.onBlur}
                  onChange={(event) => {
                    void chooseComposition(event.target.files?.[0]);
                  }}
                />
              </FormControl>
              <FormDescription>
                A self-contained .html file up to 4 MB. Its scenes are read from the data-scene
                attributes.
              </FormDescription>
              <FormMessage />
              {sceneIssues.length > 0 ? (
                <ul role="alert" className="list-disc space-y-1 pl-5 text-sm text-destructive">
                  {sceneIssues.map((issue) => (
                    <li key={issue}>{issue}</li>
                  ))}
                </ul>
              ) : null}
            </FormItem>
          )}
        />
        <section aria-labelledby="narration-heading" className="space-y-4">
          <h2 id="narration-heading" className="text-xl font-semibold">
            Narration
          </h2>
          <NarrationFields sceneIds={scenes.fields.map((scene) => scene.sceneId)} />
        </section>
        <section aria-labelledby="options-heading" className="space-y-4">
          <h2 id="options-heading" className="text-xl font-semibold">
            Options
          </h2>
          <RenderChoicesFields showVoice={mode === "synthesize"} idPrefix="upload" />
        </section>
        {failure === null ? null : (
          <p role="alert" className="text-sm text-destructive">
            {adminRenderErrorMessage(failure)}
          </p>
        )}
        <Button type="submit" disabled={create.isPending} aria-busy={create.isPending}>
          {create.isPending ? (
            <Loader2Icon aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
          ) : (
            <UploadIcon aria-hidden="true" />
          )}
          {create.isPending ? "Starting render" : "Start render"}
        </Button>
      </form>
    </Form>
  );
}
