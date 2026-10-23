"use client";

import Link from "next/link";

import { LoadingSpinner } from "@/components/shared/loading-spinner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { CancelRenderButton } from "@/features/admin-render/components/cancel-render-button";
import { CompletedPanel } from "@/features/admin-render/components/completed-panel";
import { FailurePanel } from "@/features/admin-render/components/failure-panel";
import { ProgressPanel } from "@/features/admin-render/components/progress-panel";
import { TimingsTable } from "@/features/admin-render/components/timings-table";
import { ValidationReport } from "@/features/admin-render/components/validation-report";
import { adminRenderErrorMessage } from "@/features/admin-render/errors";
import { useRenderEvents } from "@/features/admin-render/hooks/use-render-events";
import { useTestbedRender } from "@/features/admin-render/hooks/use-testbed";
import {
  POLL_INTERVAL_MS,
  type RenderProgressState,
} from "@/features/admin-render/progress-reducer";
import {
  isActiveStatus,
  parseStageTimings,
  parseValidationReport,
} from "@/features/admin-render/schemas/admin-render.schema";
import type { RenderBed, RenderStatus } from "@/features/admin-render/types/admin-render.types";
import { titleCase } from "@/lib/utils/format";

const statusVariants = {
  completed: "success",
  failed: "destructive",
  cancelled: "outline",
} as const satisfies Partial<Record<RenderStatus, "success" | "destructive" | "outline">>;

const badgeVariant = (status: RenderStatus) =>
  status === "completed" || status === "failed" || status === "cancelled"
    ? statusVariants[status]
    : "secondary";

interface RenderDetailsProps {
  render: RenderBed;
  live: RenderProgressState | null;
}

function RenderDetails({ render, live }: RenderDetailsProps) {
  const status = live?.status ?? render.status;
  const stage = live?.status ? live.stage : (render.stage ?? null);
  const progress = live?.status ? live.progress : render.progress;
  const errorCode = live?.errorCode ?? render.errorCode;
  const errorMessage = live?.errorMessage ?? render.errorMessage;
  const active = isActiveStatus(status);

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <p className="flex items-center gap-3 text-sm">
          <Badge variant={badgeVariant(status)}>{titleCase(status)}</Badge>
          <span className="font-mono text-muted-foreground">{render.id}</span>
        </p>
        <div className="flex flex-wrap gap-3">
          {active ? <CancelRenderButton renderId={render.id} /> : null}
          <Button asChild variant="outline">
            <Link href={{ pathname: "/admin/render" }}>Back to test bed</Link>
          </Button>
        </div>
      </div>
      <ProgressPanel
        status={status}
        stage={stage}
        progress={progress}
        connection={active && live !== null ? live.connection : null}
      />
      <FailurePanel status={status} errorCode={errorCode} errorMessage={errorMessage} />
      {status === "completed" ? (
        <CompletedPanel renderId={render.id} renditions={render.renditions} />
      ) : null}
      <ValidationReport report={parseValidationReport(render.validationReport)} />
      <TimingsTable timings={parseStageTimings(render.stageTimings)} />
    </div>
  );
}

function ActiveRender({ render }: { render: RenderBed }) {
  const live = useRenderEvents(render.id, { enabled: true });
  useTestbedRender(render.id, {
    pollMs: live.connection === "polling" ? POLL_INTERVAL_MS : false,
  });
  return <RenderDetails render={render} live={live} />;
}

export function RenderMonitor({ renderId }: { renderId: string }) {
  const detail = useTestbedRender(renderId);

  if (detail.isPending) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-64" />
        <LoadingSpinner label="Loading render" />
      </div>
    );
  }
  if (detail.isError) {
    return (
      <div role="alert" className="flex flex-wrap items-center gap-3 text-sm text-destructive">
        <p>{adminRenderErrorMessage(detail.error)}</p>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            void detail.refetch();
          }}
        >
          Try again
        </Button>
      </div>
    );
  }
  return isActiveStatus(detail.data.status) ? (
    <ActiveRender render={detail.data} />
  ) : (
    <RenderDetails render={detail.data} live={null} />
  );
}
