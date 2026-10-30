"use client";

import {
  DndContext,
  type DragEndEvent,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { zodResolver } from "@hookform/resolvers/zod";
import { CheckIcon, Loader2Icon, PlusIcon, SaveIcon } from "lucide-react";
import { useState } from "react";
import { useFieldArray, useForm, useWatch } from "react-hook-form";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { RegenerateDialog } from "@/features/generation/components/regenerate-dialog";
import { SceneCard } from "@/features/generation/components/scene-card";
import { generationErrorMessage } from "@/features/generation/errors";
import { useApproveJob, useSaveStoryboard } from "@/features/generation/hooks/use-storyboard";
import {
  newSceneDraft,
  sceneIndexFromField,
  type StoryboardDraft,
  storyboardDraftSchema,
  toDraft,
  toStoryboard,
  totalSeconds,
  totalVerdict,
} from "@/features/generation/schemas/storyboard.schema";
import type { StoryboardIssue, StoryboardView } from "@/features/generation/types/generation.types";
import { ApiError } from "@/lib/api/api-error";

interface StoryboardEditorProps {
  jobId: string;
  view: StoryboardView;
  onReload: () => Promise<StoryboardView | undefined>;
}

interface ServerProblem {
  sceneIndex: number | null;
  message: string;
}

const problemsFrom = (
  view: StoryboardView,
  fieldErrors: readonly { field: string; message: string }[],
): ServerProblem[] => {
  const positions = new Map(view.content.scenes.map((scene, index) => [scene.id, index]));
  const fromIssues = view.issues.map((issue: StoryboardIssue): ServerProblem => ({
    sceneIndex:
      issue.sceneId === null || issue.sceneId === undefined
        ? null
        : (positions.get(issue.sceneId) ?? null),
    message: issue.message,
  }));
  const fromFields = fieldErrors.map((error): ServerProblem => ({
    sceneIndex: sceneIndexFromField(error.field),
    message: error.message,
  }));
  return [...fromIssues, ...fromFields];
};

const TOTAL_LABELS = {
  too_long: "Warning: the scenes add up to more than the requested length.",
  too_short: "Warning: the scenes add up to less than the requested length.",
  ok: "The scenes match the requested length.",
} as const;

export function StoryboardEditor({ jobId, view, onReload }: StoryboardEditorProps) {
  const [failure, setFailure] = useState<unknown>(null);
  const [announcement, setAnnouncement] = useState("");
  const save = useSaveStoryboard(jobId);
  const approve = useApproveJob(jobId);
  const form = useForm<StoryboardDraft>({
    resolver: zodResolver(storyboardDraftSchema),
    values: toDraft(view.content),
  });
  const { control, register, formState } = form;
  const { fields, move, append, remove } = useFieldArray({
    control,
    name: "scenes",
    keyName: "fieldKey",
  });
  const scenes = useWatch({ control, name: "scenes" });
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  const { limits } = view;
  const dirty = formState.isDirty;
  const busy = save.isPending || approve.isPending;
  const total = totalSeconds(scenes);
  const requested = view.content.targetDurationMs / 1000;
  const verdict = totalVerdict(total, requested, limits.durationTolerancePercent);
  const failureError = failure === null ? null : ApiError.from(failure);
  const fieldErrors = failureError?.code === "storyboard_invalid" ? failureError.fieldErrors : [];
  const problems = problemsFrom(view, fieldErrors);
  const globalProblems = problems.filter((problem) => problem.sceneIndex === null);
  const conflict = failureError?.code === "storyboard_version_conflict";
  const blockedByIssues = !dirty && view.issues.length > 0;

  const reorder = (from: number, to: number) => {
    move(from, to);
    setAnnouncement(`Scene moved from position ${String(from + 1)} to position ${String(to + 1)}.`);
  };

  const onDragEnd = ({ active, over }: DragEndEvent) => {
    if (over === null || active.id === over.id) {
      return;
    }
    const from = fields.findIndex((field) => field.sceneId === active.id);
    const to = fields.findIndex((field) => field.sceneId === over.id);
    if (from >= 0 && to >= 0) {
      reorder(from, to);
    }
  };

  const persist = async (values: StoryboardDraft): Promise<StoryboardView | null> => {
    try {
      return await save.mutateAsync({
        content: toStoryboard(view.content, values),
        expectedVersion: view.version,
      });
    } catch (error) {
      setFailure(error);
      return null;
    }
  };

  const onSave = form.handleSubmit(async (values) => {
    setFailure(null);
    const saved = await persist(values);
    if (saved !== null) {
      setAnnouncement("Storyboard saved.");
    }
  });

  const onApprove = async () => {
    setFailure(null);
    let version = view.version;
    if (dirty) {
      const valid = await form.trigger();
      if (!valid) {
        return;
      }
      const saved = await persist(form.getValues());
      if (saved === null || saved.issues.length > 0) {
        return;
      }
      version = saved.version;
    }
    try {
      await approve.mutateAsync(version);
      setAnnouncement("Storyboard approved. Your video is being made.");
    } catch (error) {
      setFailure(error);
    }
  };

  const reload = async () => {
    setFailure(null);
    const fresh = await onReload();
    if (fresh !== undefined) {
      form.reset(toDraft(fresh.content));
    }
  };

  return (
    <form
      noValidate
      aria-label="Storyboard editor"
      className="space-y-6"
      onSubmit={(event) => {
        void onSave(event);
      }}
    >
      <p role="status" aria-live="polite" className="sr-only">
        {announcement}
      </p>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="storyboard-title">Title</Label>
          <Input
            id="storyboard-title"
            aria-invalid={formState.errors.title !== undefined}
            {...register("title")}
          />
          {formState.errors.title ? (
            <p role="alert" className="text-sm text-destructive">
              {formState.errors.title.message}
            </p>
          ) : null}
        </div>
        <div className="space-y-2">
          <Label htmlFor="storyboard-summary">Summary</Label>
          <Textarea
            id="storyboard-summary"
            rows={2}
            aria-invalid={formState.errors.summary !== undefined}
            {...register("summary")}
          />
          {formState.errors.summary ? (
            <p role="alert" className="text-sm text-destructive">
              {formState.errors.summary.message}
            </p>
          ) : null}
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-surface px-4 py-3">
        <p className="font-mono text-sm">
          {`Total ${total.toFixed(1)} s of ${requested.toFixed(0)} s requested`}
        </p>
        <p className="text-sm text-subtle-foreground">
          {TOTAL_LABELS[verdict]}
          {` Allowed range is plus or minus ${String(limits.durationTolerancePercent)} percent.`}
        </p>
      </div>
      {globalProblems.length > 0 ? (
        <ul aria-label="Storyboard problems" className="space-y-1">
          {globalProblems.map((problem) => (
            <li key={problem.message} role="alert" className="text-sm text-destructive">
              {problem.message}
            </li>
          ))}
        </ul>
      ) : null}
      {formState.errors.scenes?.root?.message ? (
        <p role="alert" className="text-sm text-destructive">
          {formState.errors.scenes.root.message}
        </p>
      ) : null}
      {formState.errors.scenes?.message ? (
        <p role="alert" className="text-sm text-destructive">
          {formState.errors.scenes.message}
        </p>
      ) : null}
      <DndContext
        sensors={sensors}
        onDragEnd={onDragEnd}
        accessibility={{
          screenReaderInstructions: {
            draggable:
              "To reorder this scene, press space, move with the arrow keys, then press space again to drop. Or use the move up and move down buttons.",
          },
          announcements: {
            onDragStart: ({ active }) =>
              `Picked up scene ${String(fields.findIndex((f) => f.sceneId === active.id) + 1)}.`,
            onDragOver: ({ active, over }) =>
              over === null
                ? ""
                : `Scene ${String(fields.findIndex((f) => f.sceneId === active.id) + 1)} is over position ${String(fields.findIndex((f) => f.sceneId === over.id) + 1)}.`,
            onDragEnd: ({ active, over }) =>
              over === null
                ? `Scene ${String(fields.findIndex((f) => f.sceneId === active.id) + 1)} was dropped.`
                : `Scene ${String(fields.findIndex((f) => f.sceneId === active.id) + 1)} was dropped at position ${String(fields.findIndex((f) => f.sceneId === over.id) + 1)}.`,
            onDragCancel: () => "Reordering cancelled.",
          },
        }}
      >
        <SortableContext
          items={fields.map((field) => field.sceneId)}
          strategy={verticalListSortingStrategy}
        >
          <ol aria-label="Scenes" className="space-y-4">
            {fields.map((field, index) => (
              <SceneCard
                key={field.sceneId}
                sceneId={field.sceneId}
                index={index}
                total={fields.length}
                control={control}
                register={register}
                errors={formState.errors}
                limits={limits}
                aspects={view.content.aspects}
                serverMessages={problems
                  .filter((problem) => problem.sceneIndex === index)
                  .map((problem) => problem.message)}
                canRemove={fields.length > limits.minScenes}
                onMove={reorder}
                onRemove={remove}
              />
            ))}
          </ol>
        </SortableContext>
      </DndContext>
      <div className="flex flex-wrap items-center gap-3">
        <Button
          type="button"
          variant="outline"
          disabled={fields.length >= limits.maxScenes}
          onClick={() => {
            append(newSceneDraft(fields.map((field) => field.sceneId)));
          }}
        >
          <PlusIcon aria-hidden="true" /> Add scene
        </Button>
        <p className="text-xs text-muted-foreground">
          {`${String(fields.length)} of ${String(limits.maxScenes)} scenes. At least ${String(limits.minScenes)} are needed.`}
        </p>
      </div>
      {failureError ? (
        <div role="alert" className="space-y-2 rounded-lg border border-destructive p-3 text-sm">
          <p className="text-destructive">{generationErrorMessage(failureError)}</p>
          {conflict ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                void reload();
              }}
            >
              Reload the latest storyboard
            </Button>
          ) : null}
        </div>
      ) : null}
      {blockedByIssues ? (
        <p className="text-sm text-subtle-foreground">
          Fix the highlighted problems and save before approving.
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" variant="outline" disabled={!dirty || busy}>
          {save.isPending ? (
            <Loader2Icon aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
          ) : (
            <SaveIcon aria-hidden="true" />
          )}
          Save changes
        </Button>
        <RegenerateDialog jobId={jobId} disabled={busy} />
        <Button
          type="button"
          disabled={busy || blockedByIssues}
          aria-busy={approve.isPending}
          onClick={() => {
            void onApprove();
          }}
        >
          {approve.isPending ? (
            <Loader2Icon aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
          ) : (
            <CheckIcon aria-hidden="true" />
          )}
          {dirty ? "Save and approve" : "Approve and continue"}
        </Button>
      </div>
    </form>
  );
}
