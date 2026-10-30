import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CreateDraftDialog } from "@/features/admin-prompts/components/create-draft-dialog";
import { DiffViewer } from "@/features/admin-prompts/components/diff-viewer";
import { TemplateDetail } from "@/features/admin-prompts/components/template-detail";
import { TemplatesTable } from "@/features/admin-prompts/components/templates-table";
import { adminPromptsErrorMessage } from "@/features/admin-prompts/errors";
import {
  describeActivationBlock,
  parseDiffLines,
  readActivationBlock,
  splitVariables,
  toDraftInput,
} from "@/features/admin-prompts/schemas/admin-prompts.schema";
import type {
  EvalRun,
  PromptTemplate,
  PromptVersion,
} from "@/features/admin-prompts/types/admin-prompts.types";
import { ApiError } from "@/lib/api/api-error";

import { jobId } from "./library-list-fixtures";
import { renderWithQuery } from "./render-with-query";

const api = vi.hoisted(() => ({
  listPromptTemplates: vi.fn(),
  listPromptVersions: vi.fn(),
  diffPromptVersions: vi.fn(),
  createPromptDraft: vi.fn(),
  activatePromptVersion: vi.fn(),
  rollbackPromptTemplate: vi.fn(),
  listEvalRuns: vi.fn(),
  startEvalRun: vi.fn(),
}));
const session = vi.hoisted(() => ({ permissions: ["prompts.manage"] as string[] }));

vi.mock("@/features/admin-prompts/api/admin-prompts.api", () => api);
vi.mock("@/features/auth/hooks/use-current-user", () => ({
  useCurrentUser: () => ({ isPending: false, data: { permissions: session.permissions } }),
}));

const KEY = "planner.storyboard";

const template = (overrides: Partial<PromptTemplate> = {}): PromptTemplate => ({
  activeVersion: 1,
  description: "Plans the storyboard",
  key: KEY,
  latestEvalStatus: "passed",
  versionCount: 2,
  ...overrides,
});

const version = (number: number, overrides: Partial<PromptVersion> = {}): PromptVersion => ({
  checksumPrefix: `abc${String(number)}def`,
  createdAt: "2026-10-20T09:00:00.000Z",
  createdBy: null,
  evalStatus: "pending",
  id: jobId(100 + number),
  isActive: false,
  version: number,
  ...overrides,
});

const run = (overrides: Partial<EvalRun> = {}): EvalRun => ({
  createdBy: null,
  datasetVersion: "2026.10",
  errorCode: null,
  finishedAt: "2026-10-21T09:10:00.000Z",
  id: jobId(200),
  modelsUsed: {},
  passed: true,
  promptVersionIds: [jobId(101)],
  scores: {},
  startedAt: "2026-10-21T09:00:00.000Z",
  status: "finished",
  suite: "safety",
  trigger: "admin",
  ...overrides,
});

const problem = (code: string, status: number, extra: Record<string, string> = {}) =>
  new ApiError({
    kind: "http",
    status,
    code,
    title: code,
    detail: null,
    extensions: extra,
  });

const seed = () => {
  api.listPromptTemplates.mockResolvedValue({ items: [template()] });
  api.listPromptVersions.mockResolvedValue({
    items: [
      version(2, { evalStatus: "pending" }),
      version(1, { isActive: true, evalStatus: "passed" }),
    ],
    nextCursor: null,
  });
  api.listEvalRuns.mockResolvedValue({ items: [run()], nextCursor: null });
};

beforeEach(() => {
  vi.clearAllMocks();
  session.permissions = ["prompts.manage"];
  vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(600);
  vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(1200);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("prompt helpers", () => {
  it("classifies unified diff lines", () => {
    expect(
      parseDiffLines(["--- v1", "+++ v2", "@@ -1 +1 @@", "-old", "+new", " same"]).map(
        (line) => line.kind,
      ),
    ).toEqual(["header", "header", "hunk", "removed", "added", "context"]);
  });

  it("reads the suites that block an activation", () => {
    const block = readActivationBlock({ missingSuites: "safety,cost", failedSuites: "planner" });

    expect(block).toEqual({ missingSuites: ["safety", "cost"], failedSuites: ["planner"] });
    expect(describeActivationBlock(block)).toContain("No passing run yet for: safety, cost.");
    expect(describeActivationBlock(block)).toContain("The latest run failed for: planner.");
    expect(readActivationBlock({})).toEqual({ missingSuites: [], failedSuites: [] });
  });

  it("explains an activation blocked by the evaluation gate", () => {
    expect(
      adminPromptsErrorMessage(problem("activation_blocked", 409, { missingSuites: "safety" })),
    ).toContain("No passing run yet for: safety.");
  });

  it("splits declared variables", () => {
    expect(splitVariables("query, audience  topic")).toEqual(["query", "audience", "topic"]);
    expect(toDraftInput({ body: "x".repeat(30), variables: "a, b" })).toEqual({
      body: "x".repeat(30),
      variables: ["a", "b"],
    });
  });
});

describe("diff viewer", () => {
  it("labels added and removed lines for screen readers", () => {
    render(
      <DiffViewer
        diff={{
          added: 1,
          removed: 1,
          fromVersion: 1,
          toVersion: 2,
          key: KEY,
          lines: ["--- v1", "+++ v2", "@@ -1 +1 @@", "-old line", "+new line", " kept"],
        }}
      />,
    );

    const diff = screen.getByRole("region", {
      name: "Unified diff of planner.storyboard from version 1 to version 2",
    });
    expect(diff).toHaveAttribute("tabindex", "0");
    expect(within(diff).getByText("Added:")).toBeInTheDocument();
    expect(within(diff).getByText("Removed:")).toBeInTheDocument();
    expect(diff).toHaveTextContent("Added: +new line");
    expect(diff).toHaveTextContent("Removed: -old line");
    expect(screen.getByText("1 lines added")).toBeInTheDocument();
  });

  it("says when two versions are identical", () => {
    render(
      <DiffViewer
        diff={{ added: 0, removed: 0, fromVersion: 1, toVersion: 2, key: KEY, lines: [] }}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent("identical");
  });
});

describe("templates table", () => {
  it("lists templates with their active version and eval status", async () => {
    api.listPromptTemplates.mockResolvedValue({
      items: [
        template(),
        template({ key: "guard.input", activeVersion: null, latestEvalStatus: null }),
      ],
    });
    renderWithQuery(<TemplatesTable />);

    const table = await screen.findByRole("table", { name: "Prompt templates" });

    expect(within(table).getByRole("link", { name: KEY })).toHaveAttribute(
      "href",
      "/admin/prompts/planner.storyboard",
    );
    expect(within(table).getByText("v1")).toBeInTheDocument();
    expect(within(table).getByText("Passed")).toBeInTheDocument();
    expect(within(table).getByText("No runs")).toBeInTheDocument();
  });

  it("reports a failed load", async () => {
    api.listPromptTemplates.mockRejectedValue(problem("forbidden", 403));
    renderWithQuery(<TemplatesTable />);

    expect(await screen.findByRole("alert")).toHaveTextContent("not allowed");
  });
});

describe("template detail", () => {
  it("shows versions with their eval status and the runs that cover them", async () => {
    seed();
    renderWithQuery(<TemplateDetail templateKey={KEY} />);

    const versions = await screen.findByRole("table", { name: "Versions of planner.storyboard" });
    expect(within(versions).getByText("Active")).toBeInTheDocument();
    expect(within(versions).getByRole("button", { name: "Activate version 1" })).toBeDisabled();

    const runs = await screen.findByRole("table", { name: "Evaluation runs" });
    expect(within(runs).getByText("safety")).toBeInTheDocument();
    expect(within(runs).getByText("v1")).toBeInTheDocument();
  });

  it("compares two versions and shows the unified diff", async () => {
    seed();
    api.diffPromptVersions.mockResolvedValue({
      added: 1,
      removed: 1,
      fromVersion: 1,
      toVersion: 2,
      key: KEY,
      lines: ["--- v1", "+++ v2", "@@ -1 +1 @@", "-before", "+after"],
    });
    renderWithQuery(<TemplateDetail templateKey={KEY} />);
    await screen.findByRole("table", { name: "Versions of planner.storyboard" });

    await userEvent.selectOptions(screen.getByLabelText("From version"), "1");
    await userEvent.selectOptions(screen.getByLabelText("To version"), "2");

    const diff = await screen.findByRole("region", { name: /Unified diff of planner.storyboard/ });
    expect(diff).toHaveTextContent("Added: +after");
    expect(api.diffPromptVersions).toHaveBeenCalledWith({ key: KEY, from: 1, to: 2 });
  });

  it("refuses to compare a version with itself", async () => {
    seed();
    renderWithQuery(<TemplateDetail templateKey={KEY} />);
    await screen.findByRole("table", { name: "Versions of planner.storyboard" });

    await userEvent.selectOptions(screen.getByLabelText("From version"), "2");
    await userEvent.selectOptions(screen.getByLabelText("To version"), "2");

    expect(await screen.findByRole("alert")).toHaveTextContent("two different versions");
    expect(api.diffPromptVersions).not.toHaveBeenCalled();
  });

  it("shows which suites block an activation", async () => {
    seed();
    api.activatePromptVersion.mockRejectedValue(
      problem("activation_blocked", 409, { missingSuites: "safety,cost", failedSuites: "planner" }),
    );
    renderWithQuery(<TemplateDetail templateKey={KEY} />);

    await userEvent.click(await screen.findByRole("button", { name: "Activate version 2" }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Activate" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "No passing run yet for: safety, cost. The latest run failed for: planner.",
    );
  });

  it("activates a version that passed its suites", async () => {
    seed();
    api.activatePromptVersion.mockResolvedValue(version(2, { isActive: true }));
    renderWithQuery(<TemplateDetail templateKey={KEY} />);

    await userEvent.click(await screen.findByRole("button", { name: "Activate version 2" }));
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Activate" }),
    );

    await waitFor(() => {
      expect(api.activatePromptVersion).toHaveBeenCalledWith(KEY, 2);
    });
  });

  it("rolls back to the previous version after confirmation", async () => {
    seed();
    api.rollbackPromptTemplate.mockResolvedValue(version(1, { isActive: true }));
    renderWithQuery(<TemplateDetail templateKey={KEY} />);

    await userEvent.click(await screen.findByRole("button", { name: "Roll back" }));
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Roll back" }),
    );

    await waitFor(() => {
      expect(api.rollbackPromptTemplate).toHaveBeenCalledWith(KEY);
    });
  });

  it("starts an evaluation run only for users with evals.run", async () => {
    seed();
    const { unmount } = renderWithQuery(<TemplateDetail templateKey={KEY} />);
    await screen.findByRole("table", { name: "Evaluation runs" });
    expect(screen.queryByRole("button", { name: "Start eval run" })).not.toBeInTheDocument();
    unmount();

    session.permissions = ["prompts.manage", "evals.run"];
    api.startEvalRun.mockResolvedValue(run({ status: "running", passed: null, finishedAt: null }));
    renderWithQuery(<TemplateDetail templateKey={KEY} />);

    await userEvent.click(await screen.findByRole("button", { name: "Start eval run" }));
    const dialog = await screen.findByRole("dialog", { name: "Start an evaluation run" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Start run" }));
    expect(await within(dialog).findByText("Choose a suite.")).toBeInTheDocument();
    expect(within(dialog).getByText("Choose at least one version.")).toBeInTheDocument();

    await userEvent.selectOptions(within(dialog).getByLabelText("Suite"), "safety");
    await userEvent.click(within(dialog).getByRole("checkbox", { name: "Version 2" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Start run" }));

    await waitFor(() => {
      expect(api.startEvalRun).toHaveBeenCalledWith({ suite: "safety", versionIds: [jobId(102)] });
    });
  });
});

describe("create draft dialog", () => {
  it("validates the text and the variable names before sending", async () => {
    renderWithQuery(<CreateDraftDialog templateKey={KEY} />);

    await userEvent.click(screen.getByRole("button", { name: "Create draft" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Prompt text"), "short");
    await userEvent.type(within(dialog).getByLabelText("Variables (optional)"), "Bad-Name");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create draft" }));

    expect(await within(dialog).findByText("Write at least 20 characters.")).toBeInTheDocument();
    expect(within(dialog).getByText(/Bad-Name is not a valid variable name/)).toBeInTheDocument();
    expect(api.createPromptDraft).not.toHaveBeenCalled();
  });

  it("shows the validation errors the API returns next to the field", async () => {
    api.createPromptDraft.mockRejectedValue(
      new ApiError({
        kind: "http",
        status: 422,
        code: "prompt_draft_invalid",
        title: "x",
        detail: null,
        fieldErrors: [{ field: "body.body", message: "Unknown variable topic", type: "x" }],
      }),
    );
    renderWithQuery(<CreateDraftDialog templateKey={KEY} />);

    await userEvent.click(screen.getByRole("button", { name: "Create draft" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(
      within(dialog).getByLabelText("Prompt text"),
      "You plan a storyboard for the topic now",
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Create draft" }));

    expect(await within(dialog).findByText("Unknown variable topic")).toBeInTheDocument();
  });

  it("explains a duplicate draft", async () => {
    api.createPromptDraft.mockRejectedValue(problem("prompt_version_exists", 409));
    renderWithQuery(<CreateDraftDialog templateKey={KEY} />);

    await userEvent.click(screen.getByRole("button", { name: "Create draft" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Prompt text"), "x".repeat(25));
    await userEvent.click(within(dialog).getByRole("button", { name: "Create draft" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent("already exists");
  });
});
