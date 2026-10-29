"use client";

import { ExternalLinkIcon } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { DetailList, DetailSection } from "@/features/admin-billing/components/detail-section";
import { JsonBlock } from "@/features/admin-billing/components/json-block";
import { StatusBadge } from "@/features/admin-billing/components/status-badge";
import { adminJobsErrorMessage } from "@/features/admin-jobs/errors";
import { useAdminJob } from "@/features/admin-jobs/hooks/use-admin-jobs";
import { adminJobsPaths } from "@/features/admin-jobs/paths";
import {
  formatMicrosUsd,
  summarizeAttempts,
  summarizeReport,
} from "@/features/admin-jobs/schemas/admin-jobs.schema";
import type {
  AdminJobDetail,
  AdminJobEvent,
  AdminJobScene,
  ReportSummary,
} from "@/features/admin-jobs/types/admin-jobs.types";
import { isHttpsUrl } from "@/features/library/schemas/library.schema";
import { formatCredits, formatDateTime } from "@/lib/utils/format";

function JobSummary({ detail }: { detail: AdminJobDetail }) {
  const { job } = detail;
  return (
    <DetailSection
      title="Job"
      actions={
        detail.traceUrl !== null && isHttpsUrl(detail.traceUrl) ? (
          <Button asChild variant="outline" size="sm">
            <a href={detail.traceUrl} target="_blank" rel="noopener noreferrer">
              Open Langfuse trace <ExternalLinkIcon aria-hidden="true" />
            </a>
          </Button>
        ) : null
      }
    >
      <div className="flex flex-wrap gap-2">
        <StatusBadge status={job.status} />
        <Badge variant="outline">{job.source}</Badge>
        {job.fallbackSceneIds.length > 0 ? (
          <Badge variant="destructive">
            {job.fallbackSceneIds.length} fallback scene
            {job.fallbackSceneIds.length === 1 ? "" : "s"}
          </Badge>
        ) : null}
      </div>
      <p className="text-sm break-words">{job.query}</p>
      {job.errorCode ? (
        <p role="status" className="text-sm text-destructive">
          <span className="font-mono">{job.errorCode}</span>
          {job.errorMessage ? `: ${job.errorMessage}` : ""}
        </p>
      ) : null}
      <DetailList
        items={[
          { label: "Job ID", value: <span className="font-mono text-xs">{job.id}</span> },
          { label: "Stage", value: <span className="font-mono">{job.currentStage ?? "-"}</span> },
          { label: "Created", value: formatDateTime(job.createdAt) },
          {
            label: "Started",
            value: job.startedAt ? formatDateTime(job.startedAt) : "Not started",
          },
          {
            label: "Completed",
            value: job.completedAt ? formatDateTime(job.completedAt) : "Not completed",
          },
          {
            label: "Parent job",
            value: job.parentJobId ? (
              <Link
                href={adminJobsPaths.job(job.parentJobId)}
                className="font-mono text-xs hover:underline"
              >
                {job.parentJobId}
              </Link>
            ) : (
              "None"
            ),
          },
          {
            label: "Options",
            value: (
              <span className="font-mono text-xs">
                {job.options.aspects.join(", ")} · {job.options.durationSeconds} s ·{" "}
                {job.options.language} · {job.options.style}
              </span>
            ),
          },
        ]}
      />
    </DetailSection>
  );
}

function CostSection({ detail }: { detail: AdminJobDetail }) {
  const { cost, job } = detail;
  return (
    <DetailSection title="Cost versus credits">
      <DetailList
        items={[
          {
            label: "Provider cost",
            value: <span className="font-mono">{formatMicrosUsd(cost.costMicrosUsd)}</span>,
          },
          {
            label: "Credits charged",
            value: (
              <span className="font-mono">
                {cost.creditsCharged === null ? "Not charged" : formatCredits(cost.creditsCharged)}
              </span>
            ),
          },
          {
            label: "Credits estimated / reserved",
            value: (
              <span className="font-mono">
                {formatCredits(job.creditsEstimated)} / {formatCredits(job.creditsReserved)}
              </span>
            ),
          },
          {
            label: "Tokens in / out",
            value: (
              <span className="font-mono">
                {formatCredits(cost.inputTokens)} / {formatCredits(cost.outputTokens)}
              </span>
            ),
          },
          {
            label: "Narration characters",
            value: <span className="font-mono">{formatCredits(cost.audioCharacters)}</span>,
          },
          {
            label: "Render time",
            value: <span className="font-mono">{(cost.renderMs / 1000).toFixed(1)} s</span>,
          },
          {
            label: "Usage records",
            value: <span className="font-mono">{formatCredits(cost.usageRecords)}</span>,
          },
        ]}
      />
    </DetailSection>
  );
}

function EventItem({ event }: { event: AdminJobEvent }) {
  const hasPayload = Object.keys(event.payload).length > 0;
  return (
    <li className="space-y-1 border-l pl-4">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <time dateTime={event.createdAt} className="font-mono text-xs text-muted-foreground">
          {formatDateTime(event.createdAt)}
        </time>
        <span className="font-mono text-sm">{event.type}</span>
        {event.stage ? (
          <span className="font-mono text-xs text-subtle-foreground">{event.stage}</span>
        ) : null}
      </div>
      {hasPayload ? (
        <details>
          <summary className="cursor-pointer rounded-sm text-xs text-muted-foreground focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none">
            Payload of {event.type}
          </summary>
          <div className="mt-2">
            <JsonBlock label={`Payload of ${event.type}`} value={event.payload} />
          </div>
        </details>
      ) : null}
    </li>
  );
}

function EventsSection({ events }: { events: readonly AdminJobEvent[] }) {
  return (
    <DetailSection title="Events">
      {events.length === 0 ? (
        <p className="text-sm text-muted-foreground">No events were recorded.</p>
      ) : (
        <ol aria-label="Job events" className="space-y-3">
          {events.map((event) => (
            <EventItem key={event.id} event={event} />
          ))}
        </ol>
      )}
    </DetailSection>
  );
}

function StoryboardsSection({ detail }: { detail: AdminJobDetail }) {
  return (
    <DetailSection title="Storyboard versions">
      {detail.storyboardVersions.length === 0 ? (
        <p className="text-sm text-muted-foreground">No storyboard has been written yet.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">Version</TableHead>
              <TableHead scope="col">Origin</TableHead>
              <TableHead scope="col">Approved</TableHead>
              <TableHead scope="col">Created</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {detail.storyboardVersions.map((version) => (
              <TableRow key={version.version}>
                <TableCell className="font-mono">v{version.version}</TableCell>
                <TableCell className="font-mono">{version.origin}</TableCell>
                <TableCell>
                  <Badge variant={version.approved ? "success" : "outline"}>
                    {version.approved ? "Approved" : "Not approved"}
                  </Badge>
                </TableCell>
                <TableCell>{formatDateTime(version.createdAt)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {detail.approvedStoryboard ? (
        <p className="text-sm text-muted-foreground">
          Approved storyboard: {detail.approvedStoryboard.scenes.length} scenes,{" "}
          {Math.round(detail.approvedStoryboard.targetDurationMs / 1000)} s target,{" "}
          {detail.approvedStoryboard.styleSkill} style.
        </p>
      ) : null}
    </DetailSection>
  );
}

function SceneRow({ scene }: { scene: AdminJobScene }) {
  const attempts = summarizeAttempts(scene);
  return (
    <TableRow>
      <TableCell className="font-mono">{scene.position + 1}</TableCell>
      <TableCell className="font-mono">{scene.sceneId}</TableCell>
      <TableCell>
        <div className="flex flex-wrap gap-1">
          <StatusBadge status={scene.status} />
          {scene.isFallback ? <Badge variant="destructive">Fallback</Badge> : null}
        </div>
        {scene.errorCode ? (
          <p className="mt-1 font-mono text-xs text-destructive">{scene.errorCode}</p>
        ) : null}
      </TableCell>
      <TableCell className="font-mono">{scene.repairAttempts}</TableCell>
      <TableCell className="font-mono">
        {scene.actualDurationMs === null ? "-" : `${(scene.actualDurationMs / 1000).toFixed(1)} s`}
      </TableCell>
      <TableCell>
        {attempts.length === 0 ? (
          <span className="text-muted-foreground">No attempts</span>
        ) : (
          <ol aria-label={`Attempts for ${scene.sceneId}`} className="space-y-1 text-xs">
            {attempts.map((attempt) => (
              <li key={attempt.attempt} className="font-mono">
                #{attempt.attempt} {attempt.kind}
                {attempt.issueCodes.length > 0 ? `: ${attempt.issueCodes.join(", ")}` : ""}
              </li>
            ))}
          </ol>
        )}
      </TableCell>
    </TableRow>
  );
}

function ScenesSection({ scenes }: { scenes: readonly AdminJobScene[] }) {
  return (
    <DetailSection title="Scenes">
      {scenes.length === 0 ? (
        <p className="text-sm text-muted-foreground">No scenes have been generated yet.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">#</TableHead>
              <TableHead scope="col">Scene</TableHead>
              <TableHead scope="col">Status</TableHead>
              <TableHead scope="col">Repairs</TableHead>
              <TableHead scope="col">Duration</TableHead>
              <TableHead scope="col">Attempt log</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {scenes.map((scene) => (
              <SceneRow key={scene.sceneId} scene={scene} />
            ))}
          </TableBody>
        </Table>
      )}
    </DetailSection>
  );
}

function ReportBlock({ title, summary }: { title: string; summary: ReportSummary | null }) {
  if (summary === null) {
    return (
      <div className="space-y-2">
        <h3 className="text-sm font-medium">{title}</h3>
        <p className="text-sm text-muted-foreground">Not recorded.</p>
      </div>
    );
  }
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium">{title}</h3>
      <p className="font-mono text-xs text-subtle-foreground">
        {summary.valid === null ? "" : summary.valid ? "valid · " : "invalid · "}
        {summary.errors === null ? "" : `${summary.errors} errors · `}
        {summary.warnings === null ? "" : `${summary.warnings} warnings · `}
        {summary.skipped > 0 ? `${summary.skipped} skipped · ` : ""}
        {summary.issueCounts.reduce((total, item) => total + item.count, 0)} issues
      </p>
      {summary.issueCounts.length === 0 ? (
        <p className="text-sm text-muted-foreground">No issues.</p>
      ) : (
        <Table aria-label={`${title} issue codes`}>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">Issue code</TableHead>
              <TableHead scope="col">Count</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {summary.issueCounts.map((item) => (
              <TableRow key={item.code}>
                <TableCell className="font-mono">{item.code}</TableCell>
                <TableCell className="font-mono">{item.count}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}

function ReportsSection({ reports }: { reports: AdminJobDetail["reports"] }) {
  return (
    <DetailSection title="Validation and review">
      <div className="grid gap-6 lg:grid-cols-2">
        <ReportBlock title="Validation report" summary={summarizeReport(reports["validation"])} />
        <ReportBlock title="Visual review" summary={summarizeReport(reports["review"])} />
      </div>
    </DetailSection>
  );
}

export function JobDetail({ jobId }: { jobId: string }) {
  const job = useAdminJob(jobId);
  if (job.isPending) {
    return <Skeleton role="status" aria-hidden={false} aria-label="Loading job" className="h-96" />;
  }
  if (job.isError) {
    return (
      <div role="alert" className="flex flex-wrap items-center gap-3 text-sm text-destructive">
        <p>{adminJobsErrorMessage(job.error)}</p>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            void job.refetch();
          }}
        >
          Try again
        </Button>
      </div>
    );
  }
  return (
    <div className="space-y-6">
      <JobSummary detail={job.data} />
      <CostSection detail={job.data} />
      <EventsSection events={job.data.events} />
      <StoryboardsSection detail={job.data} />
      <ScenesSection scenes={job.data.scenes} />
      <ReportsSection reports={job.data.reports} />
    </div>
  );
}
