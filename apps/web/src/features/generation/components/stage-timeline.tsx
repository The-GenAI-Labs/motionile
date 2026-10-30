"use client";

import {
  BanIcon,
  CheckIcon,
  CircleDotIcon,
  CircleIcon,
  MinusIcon,
  TriangleAlertIcon,
} from "lucide-react";

import { POLL_INTERVAL_MS } from "@/features/generation/api/job-events.api";
import { useJobEventList } from "@/features/generation/hooks/use-job";
import { useJobConnection } from "@/features/generation/store/job-ui.store";
import { buildTimeline, statusLabels } from "@/features/generation/timeline";
import type {
  ConnectionState,
  Job,
  TimelineStatus,
} from "@/features/generation/types/generation.types";
import { formatDurationMs } from "@/lib/utils/format";

const connectionLabels = {
  connecting: "Connecting to live updates",
  live: "Live updates connected",
  reconnecting: "Live updates lost. Reconnecting",
  polling: `Live updates unavailable. Checking every ${String(POLL_INTERVAL_MS / 1000)} seconds`,
} as const satisfies Record<ConnectionState, string>;

const icons = {
  pending: CircleIcon,
  active: CircleDotIcon,
  done: CheckIcon,
  skipped: MinusIcon,
  failed: TriangleAlertIcon,
  cancelled: BanIcon,
} as const satisfies Record<TimelineStatus, typeof CircleIcon>;

const iconColors = {
  pending: "text-muted-foreground",
  active: "text-foreground",
  done: "text-success",
  skipped: "text-muted-foreground",
  failed: "text-destructive",
  cancelled: "text-muted-foreground",
} as const satisfies Record<TimelineStatus, string>;

export function StageTimeline({ job }: { job: Job }) {
  const events = useJobEventList(job.id);
  const connection = useJobConnection(job.id);
  const timeline = buildTimeline(job, events);
  const percent = Math.round(timeline.renderProgress);
  const rendering = timeline.rows.find((row) => row.key === "render")?.status !== "pending";
  return (
    <section aria-labelledby="timeline-heading" className="space-y-4">
      <h2 id="timeline-heading" className="text-xl font-semibold">
        Progress
      </h2>
      <p role="status" aria-live="polite" className="sr-only">
        {timeline.announcement}
      </p>
      <ol role="list" aria-label="Video stages" className="space-y-2">
        {timeline.rows.map((row) => {
          const Icon = icons[row.status];
          return (
            <li
              key={row.key}
              aria-current={row.status === "active" ? "step" : undefined}
              className="flex items-start gap-3 rounded-lg border bg-surface px-3 py-2"
            >
              <Icon
                aria-hidden="true"
                className={`mt-0.5 size-4 shrink-0 ${iconColors[row.status]}`}
              />
              <div className="min-w-0 flex-1">
                <p
                  className={
                    row.status === "pending" || row.status === "skipped"
                      ? "text-sm text-muted-foreground"
                      : "text-sm font-medium"
                  }
                >
                  {row.label}
                  <span className="ml-2 font-mono text-xs text-subtle-foreground">
                    {statusLabels[row.status]}
                  </span>
                </p>
                {row.detail ? <p className="text-xs text-subtle-foreground">{row.detail}</p> : null}
              </div>
              {row.durationMs === null ? null : (
                <span className="font-mono text-xs text-muted-foreground">
                  {formatDurationMs(row.durationMs)}
                </span>
              )}
            </li>
          );
        })}
      </ol>
      {rendering ? (
        <div className="space-y-1">
          <div
            role="progressbar"
            aria-label="Render progress"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={percent}
            aria-valuetext={`${String(percent)} percent rendered`}
            className="h-3 w-full overflow-hidden rounded-full bg-elevated"
          >
            <div
              aria-hidden="true"
              className="h-full bg-success transition-[width] duration-300 motion-reduce:transition-none"
              style={{ width: `${String(percent)}%` }}
            />
          </div>
          <p className="font-mono text-xs text-subtle-foreground">{`${String(percent)}% rendered`}</p>
        </div>
      ) : null}
      {connection === null ? null : (
        <p className="text-xs text-muted-foreground">{connectionLabels[connection]}</p>
      )}
    </section>
  );
}
