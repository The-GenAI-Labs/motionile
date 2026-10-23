import { CheckIcon, CircleDotIcon, CircleIcon } from "lucide-react";

import { POLL_INTERVAL_MS } from "@/features/admin-render/progress-reducer";
import { renderStages, stageLabels } from "@/features/admin-render/schemas/admin-render.schema";
import type {
  ConnectionState,
  RenderStage,
  RenderStatus,
} from "@/features/admin-render/types/admin-render.types";
import { titleCase } from "@/lib/utils/format";

interface ProgressPanelProps {
  status: RenderStatus;
  stage: RenderStage | null;
  progress: number;
  connection: ConnectionState | null;
}

const connectionLabels = {
  connecting: "Connecting to live updates",
  live: "Live updates connected",
  reconnecting: "Live updates lost. Reconnecting",
  polling: `Live updates unavailable. Checking every ${String(POLL_INTERVAL_MS / 1000)} seconds`,
} as const satisfies Record<ConnectionState, string>;

const stageState = (
  stage: RenderStage,
  current: RenderStage | null,
  status: RenderStatus,
): "done" | "current" | "pending" => {
  if (status === "completed") {
    return "done";
  }
  if (current === null) {
    return "pending";
  }
  const index = renderStages.indexOf(stage);
  const currentIndex = renderStages.indexOf(current);
  if (index < currentIndex) {
    return "done";
  }
  return index === currentIndex ? "current" : "pending";
};

export function ProgressPanel({ status, stage, progress, connection }: ProgressPanelProps) {
  const percent = Math.round(progress);
  const stageText = stage === null ? titleCase(status) : stageLabels[stage];
  return (
    <section aria-labelledby="progress-heading" className="space-y-4">
      <h2 id="progress-heading" className="text-xl font-semibold">
        Progress
      </h2>
      <div
        role="progressbar"
        aria-label="Render progress"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        aria-valuetext={`${stageText}, ${String(percent)} percent`}
        className="h-3 w-full overflow-hidden rounded-full bg-elevated"
      >
        <div
          aria-hidden="true"
          className="h-full bg-success transition-[width] duration-300 motion-reduce:transition-none"
          style={{ width: `${String(percent)}%` }}
        />
      </div>
      <p className="font-mono text-sm">{`${stageText} ${String(percent)}%`}</p>
      <p role="status" aria-live="polite" className="sr-only">
        {`${stageText}. ${String(percent)} percent complete.`}
      </p>
      <ol aria-label="Render stages" className="grid gap-2 sm:grid-cols-3">
        {renderStages.map((name) => {
          const state = stageState(name, stage, status);
          return (
            <li
              key={name}
              aria-current={state === "current" ? "step" : undefined}
              className={
                state === "pending"
                  ? "flex items-center gap-2 text-sm text-muted-foreground"
                  : "flex items-center gap-2 text-sm"
              }
            >
              {state === "done" ? (
                <CheckIcon aria-hidden="true" className="size-4 text-success" />
              ) : state === "current" ? (
                <CircleDotIcon aria-hidden="true" className="size-4" />
              ) : (
                <CircleIcon aria-hidden="true" className="size-4" />
              )}
              {stageLabels[name]}
              <span className="sr-only">
                {state === "done" ? " (done)" : state === "current" ? " (current)" : " (waiting)"}
              </span>
            </li>
          );
        })}
      </ol>
      {connection === null ? null : (
        <p className="text-xs text-muted-foreground">{connectionLabels[connection]}</p>
      )}
    </section>
  );
}
