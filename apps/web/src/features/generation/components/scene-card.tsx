"use client";

import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import {
  ArrowDownIcon,
  ArrowUpIcon,
  GripVerticalIcon,
  Trash2Icon,
  TriangleAlertIcon,
} from "lucide-react";
import { type Control, type FieldErrors, type UseFormRegister, useWatch } from "react-hook-form";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  onScreenCharacterLimit,
  onScreenCharacters,
  rateVerdict,
  spokenSeconds,
  type StoryboardDraft,
  wordCount,
} from "@/features/generation/schemas/storyboard.schema";
import type { Aspect, StoryboardLimits } from "@/features/generation/types/generation.types";

interface SceneCardProps {
  sceneId: string;
  index: number;
  total: number;
  control: Control<StoryboardDraft>;
  register: UseFormRegister<StoryboardDraft>;
  errors: FieldErrors<StoryboardDraft>;
  limits: StoryboardLimits;
  aspects: readonly Aspect[];
  serverMessages: readonly string[];
  canRemove: boolean;
  onMove: (from: number, to: number) => void;
  onRemove: (index: number) => void;
}

function FieldMessage({ id, message }: { id: string; message: string | undefined }) {
  return message === undefined ? null : (
    <p id={id} role="alert" className="text-sm text-destructive">
      {message}
    </p>
  );
}

function SceneHints({
  control,
  index,
  limits,
  aspects,
}: Pick<SceneCardProps, "control" | "index" | "limits" | "aspects">) {
  const scene = useWatch({ control, name: `scenes.${String(index)}` as `scenes.${number}` });
  const verdict = rateVerdict(scene.narration, scene.durationSeconds, limits);
  const spoken = spokenSeconds(scene.narration, limits);
  const characterLimit = onScreenCharacterLimit(limits, aspects);
  const characters = onScreenCharacters(scene.onScreenText);
  return (
    <div className="space-y-1 text-xs text-subtle-foreground">
      <p>
        {`${String(wordCount(scene.narration))} words, about ${spoken.toFixed(1)} seconds spoken at ${limits.nominalWordsPerSecond.toFixed(1)} words per second`}
      </p>
      {verdict === "ok" ? null : (
        <p className="flex items-center gap-1 text-foreground">
          <TriangleAlertIcon aria-hidden="true" className="size-3" />
          {verdict === "too_fast"
            ? `Warning: too many words for ${String(scene.durationSeconds)} seconds. Shorten the narration or lengthen the scene.`
            : `Warning: too few words for ${String(scene.durationSeconds)} seconds. Add narration or shorten the scene.`}
        </p>
      )}
      {characterLimit !== null && characters > characterLimit ? (
        <p className="flex items-center gap-1 text-foreground">
          <TriangleAlertIcon aria-hidden="true" className="size-3" />
          {`Warning: ${String(characters)} characters of on-screen text, the limit is ${String(characterLimit)}.`}
        </p>
      ) : null}
    </div>
  );
}

export function SceneCard(props: SceneCardProps) {
  const sortable = useSortable({ id: props.sceneId });
  return renderScene(props, sortable);
}

function renderScene(
  {
    sceneId,
    index,
    total,
    control,
    register,
    errors,
    limits,
    aspects,
    serverMessages,
    canRemove,
    onMove,
    onRemove,
  }: SceneCardProps,
  sortable: ReturnType<typeof useSortable>,
) {
  const number = index + 1;
  const sceneErrors = errors.scenes?.[index];
  const field = (name: string) => `${sceneId}-${name}`;
  return (
    <li
      ref={sortable.setNodeRef}
      style={{
        transform: CSS.Transform.toString(sortable.transform),
        transition: sortable.transition,
      }}
      aria-label={`Scene ${String(number)} of ${String(total)}`}
      className="space-y-4 rounded-xl border bg-surface p-4 data-[dragging=true]:opacity-70"
      data-dragging={sortable.isDragging}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-mono text-sm">{`Scene ${String(number)}`}</h3>
        <div className="flex items-center gap-1">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={`Drag scene ${String(number)} to reorder`}
            {...sortable.attributes}
            {...sortable.listeners}
          >
            <GripVerticalIcon aria-hidden="true" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={`Move scene ${String(number)} up`}
            disabled={index === 0}
            onClick={() => {
              onMove(index, index - 1);
            }}
          >
            <ArrowUpIcon aria-hidden="true" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={`Move scene ${String(number)} down`}
            disabled={index === total - 1}
            onClick={() => {
              onMove(index, index + 1);
            }}
          >
            <ArrowDownIcon aria-hidden="true" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={`Remove scene ${String(number)}`}
            disabled={!canRemove}
            onClick={() => {
              onRemove(index);
            }}
          >
            <Trash2Icon aria-hidden="true" />
          </Button>
        </div>
      </div>
      {serverMessages.length > 0 ? (
        <ul aria-label={`Problems with scene ${String(number)}`} className="space-y-1">
          {serverMessages.map((message) => (
            <li key={message} role="alert" className="text-sm text-destructive">
              {message}
            </li>
          ))}
        </ul>
      ) : null}
      <div className="space-y-2">
        <Label htmlFor={field("goal")}>{`Scene ${String(number)} goal`}</Label>
        <Input
          id={field("goal")}
          aria-invalid={sceneErrors?.goal !== undefined}
          aria-describedby={field("goal-error")}
          {...register(`scenes.${index}.goal`)}
        />
        <FieldMessage id={field("goal-error")} message={sceneErrors?.goal?.message} />
      </div>
      <div className="space-y-2">
        <Label htmlFor={field("narration")}>{`Scene ${String(number)} narration`}</Label>
        <Textarea
          id={field("narration")}
          rows={3}
          aria-invalid={sceneErrors?.narration !== undefined}
          aria-describedby={field("narration-error")}
          {...register(`scenes.${index}.narration`)}
        />
        <FieldMessage id={field("narration-error")} message={sceneErrors?.narration?.message} />
        <SceneHints control={control} index={index} limits={limits} aspects={aspects} />
      </div>
      <div className="space-y-2">
        <Label htmlFor={field("visual")}>{`Scene ${String(number)} visual brief`}</Label>
        <Textarea
          id={field("visual")}
          rows={3}
          aria-invalid={sceneErrors?.visualBrief !== undefined}
          aria-describedby={field("visual-error")}
          {...register(`scenes.${index}.visualBrief`)}
        />
        <FieldMessage id={field("visual-error")} message={sceneErrors?.visualBrief?.message} />
      </div>
      <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_10rem]">
        <div className="space-y-2">
          <Label
            htmlFor={field("text")}
          >{`Scene ${String(number)} on-screen text (one line each)`}</Label>
          <Textarea
            id={field("text")}
            rows={2}
            aria-invalid={sceneErrors?.onScreenText !== undefined}
            aria-describedby={field("text-error")}
            {...register(`scenes.${index}.onScreenText`)}
          />
          <FieldMessage id={field("text-error")} message={sceneErrors?.onScreenText?.message} />
        </div>
        <div className="space-y-2">
          <Label htmlFor={field("seconds")}>{`Scene ${String(number)} length in seconds`}</Label>
          <Input
            id={field("seconds")}
            type="number"
            inputMode="decimal"
            min={1}
            max={120}
            step={0.5}
            aria-invalid={sceneErrors?.durationSeconds !== undefined}
            aria-describedby={field("seconds-error")}
            {...register(`scenes.${index}.durationSeconds`, { valueAsNumber: true })}
          />
          <FieldMessage
            id={field("seconds-error")}
            message={sceneErrors?.durationSeconds?.message}
          />
        </div>
      </div>
    </li>
  );
}
