import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NuqsTestingAdapter } from "nuqs/adapters/testing";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { JobDetail } from "@/features/admin-jobs/components/job-detail";
import { JobsAnalyticsPanel } from "@/features/admin-jobs/components/jobs-analytics";
import { JobsTable } from "@/features/admin-jobs/components/jobs-table";
import {
  countIssueCodes,
  summarizeAttempts,
  summarizeReport,
} from "@/features/admin-jobs/schemas/admin-jobs.schema";
import type {
  AdminJobDetail,
  AdminJobSummary,
  JobAnalytics,
} from "@/features/admin-jobs/types/admin-jobs.types";
import { ApiError } from "@/lib/api/api-error";

import { activeJob, jobId } from "./library-list-fixtures";
import { renderWithQuery } from "./render-with-query";

const api = vi.hoisted(() => ({
  listAdminJobs: vi.fn(),
  getAdminJob: vi.fn(),
  getJobAnalytics: vi.fn(),
}));

vi.mock("@/features/admin-jobs/api/admin-jobs.api", () => api);

const withNuqs = (ui: ReactElement, searchParams = "") => (
  <NuqsTestingAdapter searchParams={searchParams}>{ui}</NuqsTestingAdapter>
);

const summary = (overrides: Partial<AdminJobSummary> = {}): AdminJobSummary => ({
  completedAt: null,
  createdAt: "2026-10-25T09:00:00.000Z",
  creditsCharged: null,
  creditsEstimated: 60,
  creditsReserved: 60,
  currentStage: "voice",
  errorCode: null,
  id: jobId(1),
  parentJobId: null,
  query: "Explain TCP handshakes",
  source: "query",
  status: "voicing",
  userId: "0197c5a2-1b2c-7d3e-8f40-5a6b7c8dd001",
  ...overrides,
});

const detail = (overrides: Partial<AdminJobDetail> = {}): AdminJobDetail => ({
  approvedStoryboard: null,
  cost: {
    audioCharacters: 1200,
    costMicrosUsd: 123_456,
    creditsCharged: 70,
    inputTokens: 5000,
    outputTokens: 2500,
    renderMs: 42_000,
    usageRecords: 9,
  },
  events: [
    {
      id: jobId(11),
      type: "scene.fallback",
      stage: "repair",
      payload: { sceneId: "intro", reason: "max_repairs" },
      createdAt: "2026-10-25T09:02:00.000Z",
    },
    {
      id: jobId(12),
      type: "job.completed",
      stage: null,
      payload: {},
      createdAt: "2026-10-25T09:05:00.000Z",
    },
  ],
  job: activeJob({ status: "completed", fallbackSceneIds: ["intro"], errorCode: null }),
  reports: {
    validation: {
      valid: false,
      errors: 2,
      warnings: 1,
      issues: [{ code: "text_overflow" }, { code: "text_overflow" }, { code: "low_contrast" }],
    },
    review: { issues: [{ code: "illegible" }], skipped: [{ sceneId: "outro", code: "x" }] },
  },
  scenes: [
    {
      actualDurationMs: 8200,
      attemptLog: [
        { attempt: 1, kind: "initial", issueCodes: ["text_overflow"] },
        { attempt: 2, kind: "fallback", issueCodes: [] },
      ],
      errorCode: null,
      isFallback: true,
      position: 0,
      repairAttempts: 1,
      sceneId: "intro",
      status: "generated",
    },
  ],
  storyboardVersions: [
    { approved: false, createdAt: "2026-10-25T09:01:00.000Z", origin: "planner", version: 1 },
    { approved: true, createdAt: "2026-10-25T09:01:30.000Z", origin: "critic", version: 2 },
  ],
  traceUrl: "https://langfuse.motionile.test/project/p1/traces/t1",
  ...overrides,
});

const analytics = (overrides: Partial<JobAnalytics> = {}): JobAnalytics => ({
  averageCostMicrosUsd: 150_000,
  averageCreditsCharged: 72.5,
  dateFrom: "2026-10-01",
  dateTo: "2026-10-02",
  days: [
    { day: "2026-10-01", completed: 8, failed: 1, cancelled: 1, successRate: 0.8 },
    { day: "2026-10-02", completed: 5, failed: 0, cancelled: 0, successRate: 1 },
  ],
  fallbackRate: 0.05,
  repairRate: 0.2,
  scenes: 120,
  stages: [{ stage: "scenes", averageSeconds: 31.5, samples: 13 }],
  successRate: 0.9,
  ...overrides,
});

const problem = (code: string, status: number) =>
  new ApiError({ kind: "http", status, code, title: code, detail: null });

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(600);
  vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(1200);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("report summaries", () => {
  it("counts issue codes by frequency", () => {
    expect(countIssueCodes(["b", "a", "b"])).toEqual([
      { code: "b", count: 2 },
      { code: "a", count: 1 },
    ]);
  });

  it("summarizes a validation report and tolerates unknown shapes", () => {
    expect(
      summarizeReport({ valid: true, errors: 0, warnings: 1, issues: [{ code: "x" }, {}] }),
    ).toEqual({
      valid: true,
      errors: 0,
      warnings: 1,
      issueCounts: [
        { code: "unknown", count: 1 },
        { code: "x", count: 1 },
      ],
      skipped: 0,
    });
    expect(summarizeReport("nope")).toBeNull();
  });

  it("reads attempt logs defensively", () => {
    const scene = detail().scenes.at(0);
    if (scene === undefined) {
      throw new Error("the fixture has a scene");
    }
    expect(
      summarizeAttempts({
        ...scene,
        attemptLog: [{ kind: "repair" }, { bad: 1 }],
      }),
    ).toEqual([
      { attempt: 1, kind: "repair", issueCodes: [] },
      { attempt: 2, kind: "unknown", issueCodes: [] },
    ]);
  });
});

describe("jobs table", () => {
  it("lists jobs with links to their detail", async () => {
    api.listAdminJobs.mockResolvedValue({
      items: [summary(), summary({ id: jobId(2), status: "failed", errorCode: "tts_failed" })],
      nextCursor: null,
    });
    renderWithQuery(withNuqs(<JobsTable />));

    const table = await screen.findByRole("table", { name: "Jobs" });

    expect(
      within(table).getAllByRole("link", { name: "Explain TCP handshakes" })[0],
    ).toHaveAttribute("href", `/admin/jobs/${jobId(1)}`);
    expect(within(table).getByText("tts_failed")).toBeInTheDocument();
    expect(within(table).getByText("Failed")).toBeInTheDocument();
  });

  it("applies the filters from the url, ignoring an invalid user id", async () => {
    api.listAdminJobs.mockResolvedValue({ items: [], nextCursor: null });
    renderWithQuery(
      withNuqs(<JobsTable />, "?status=failed&source=mcp&user=not-a-uuid&from=2026-10-01"),
    );

    await screen.findByText("No jobs match these filters.");

    expect(api.listAdminJobs).toHaveBeenCalledWith(
      { status: "failed", source: "mcp", createdFrom: "2026-10-01T00:00:00.000Z" },
      undefined,
    );
    expect(screen.getByLabelText("Status")).toHaveValue("failed");
  });

  it("reports a failure and can retry", async () => {
    api.listAdminJobs
      .mockRejectedValueOnce(problem("forbidden", 403))
      .mockResolvedValueOnce({ items: [summary()], nextCursor: null });
    renderWithQuery(withNuqs(<JobsTable />));

    expect(await screen.findByRole("alert")).toHaveTextContent("not allowed to read every user");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("table", { name: "Jobs" })).toBeInTheDocument();
  });
});

describe("job detail", () => {
  it("shows the events timeline, storyboards, scenes and reports", async () => {
    api.getAdminJob.mockResolvedValue(detail());
    renderWithQuery(<JobDetail jobId={jobId(1)} />);

    const events = await screen.findByRole("list", { name: "Job events" });
    expect(within(events).getAllByRole("listitem")).toHaveLength(2);
    expect(within(events).getByText("scene.fallback")).toBeInTheDocument();
    expect(within(events).getByText("Payload of scene.fallback")).toBeInTheDocument();

    const storyboards = screen.getByRole("region", { name: "Storyboard versions" });
    expect(within(storyboards).getByRole("cell", { name: "Approved" })).toBeInTheDocument();
    expect(within(storyboards).getByRole("cell", { name: "Not approved" })).toBeInTheDocument();

    const scenes = screen.getByRole("region", { name: "Scenes" });
    expect(within(scenes).getByText("Fallback")).toBeInTheDocument();
    const attempts = within(scenes).getByRole("list", { name: "Attempts for intro" });
    expect(within(attempts).getByText("#1 initial: text_overflow")).toBeInTheDocument();

    const reports = screen.getByRole("region", { name: "Validation and review" });
    const validation = within(reports).getByRole("table", {
      name: "Validation report issue codes",
    });
    expect(within(validation).getByRole("row", { name: "text_overflow 2" })).toBeInTheDocument();
    expect(within(validation).getByRole("row", { name: "low_contrast 1" })).toBeInTheDocument();
    expect(within(reports).getByText(/1 skipped/)).toBeInTheDocument();
  });

  it("compares provider cost with the credits charged", async () => {
    api.getAdminJob.mockResolvedValue(detail());
    renderWithQuery(<JobDetail jobId={jobId(1)} />);

    const cost = await screen.findByRole("region", { name: "Cost versus credits" });

    expect(within(cost).getByText("$0.1235")).toBeInTheDocument();
    expect(within(cost).getByText("70")).toBeInTheDocument();
    expect(within(cost).getByText("42.0 s")).toBeInTheDocument();
  });

  it("links to the Langfuse trace only for an https url", async () => {
    api.getAdminJob.mockResolvedValue(detail());
    const { unmount } = renderWithQuery(<JobDetail jobId={jobId(1)} />);

    const link = await screen.findByRole("link", { name: /Open Langfuse trace/ });
    expect(link).toHaveAttribute("href", "https://langfuse.motionile.test/project/p1/traces/t1");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    unmount();

    api.getAdminJob.mockResolvedValue(detail({ traceUrl: "javascript:alert(1)" }));
    renderWithQuery(<JobDetail jobId={jobId(1)} />);
    await screen.findByRole("region", { name: "Job" });
    expect(screen.queryByRole("link", { name: /Langfuse/ })).not.toBeInTheDocument();
  });

  it("says when reports were not recorded", async () => {
    api.getAdminJob.mockResolvedValue(detail({ reports: {}, events: [], scenes: [] }));
    renderWithQuery(<JobDetail jobId={jobId(1)} />);

    expect(await screen.findAllByText("Not recorded.")).toHaveLength(2);
    expect(screen.getByText("No events were recorded.")).toBeInTheDocument();
    expect(screen.getByText("No scenes have been generated yet.")).toBeInTheDocument();
  });

  it("explains a missing job", async () => {
    api.getAdminJob.mockRejectedValue(problem("job_not_found", 404));
    renderWithQuery(<JobDetail jobId={jobId(1)} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("no longer exists");
  });
});

describe("jobs analytics", () => {
  it("summarizes outcomes, stage timings and cost for the range", async () => {
    api.getJobAnalytics.mockResolvedValue(analytics());
    renderWithQuery(withNuqs(<JobsAnalyticsPanel />));

    const panel = await screen.findByRole("region", { name: "Generation analytics" });

    expect(within(panel).getByText("90.0%")).toBeInTheDocument();
    expect(within(panel).getByText("20.0%")).toBeInTheDocument();
    expect(within(panel).getByText("5.0%")).toBeInTheDocument();
    expect(within(panel).getByText("$0.1500 cost, 72.5 credits charged")).toBeInTheDocument();
    expect(within(panel).getByRole("img", { name: /Jobs per day/ })).toBeInTheDocument();
    expect(
      within(within(panel).getByRole("table", { name: "Average time per stage" })).getByText(
        "31.5 s",
      ),
    ).toBeInTheDocument();
  });

  it("shows no data for rates that cannot be computed", async () => {
    api.getJobAnalytics.mockResolvedValue(
      analytics({
        successRate: null,
        repairRate: null,
        fallbackRate: null,
        averageCostMicrosUsd: null,
        days: [],
        stages: [],
      }),
    );
    renderWithQuery(withNuqs(<JobsAnalyticsPanel />));

    expect(await screen.findAllByText("No data")).toHaveLength(4);
  });

  it("requests the range chosen in the url", async () => {
    api.getJobAnalytics.mockResolvedValue(analytics());
    renderWithQuery(withNuqs(<JobsAnalyticsPanel />, "?statsFrom=2026-10-01&statsTo=2026-10-07"));

    await waitFor(() => {
      expect(api.getJobAnalytics).toHaveBeenCalledWith({ from: "2026-10-01", to: "2026-10-07" });
    });
  });
});
