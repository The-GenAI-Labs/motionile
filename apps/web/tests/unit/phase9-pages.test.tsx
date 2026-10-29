import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as adminJob from "@/app/(super-admin)/admin/jobs/[jobId]/page";
import * as adminJobs from "@/app/(super-admin)/admin/jobs/page";
import * as adminPromptTemplate from "@/app/(super-admin)/admin/prompts/[key]/page";
import * as adminPrompts from "@/app/(super-admin)/admin/prompts/page";
import * as adminSkill from "@/app/(super-admin)/admin/skills/[slug]/page";
import * as adminSkills from "@/app/(super-admin)/admin/skills/page";
import * as library from "@/app/(user)/library/page";
import robots from "@/app/robots";
import { adminNavigation, crawlerDisallowedPaths } from "@/config/navigation";

const { notFound, requirePermissions } = vi.hoisted(() => ({
  notFound: vi.fn(() => {
    throw new Error("NEXT_NOT_FOUND");
  }),
  requirePermissions: vi.fn(() => Promise.resolve()),
}));

vi.mock("next/navigation", () => ({ notFound }));
vi.mock("@/lib/auth/require-permissions", () => ({ requirePermissions }));
vi.mock("@/features/admin-jobs/components/jobs-analytics", () => ({
  JobsAnalyticsPanel: () => <div role="region" aria-label="Generation analytics" />,
}));
vi.mock("@/features/admin-jobs/components/jobs-table", () => ({
  JobsTable: () => <div role="region" aria-label="Jobs table" />,
}));
vi.mock("@/features/admin-jobs/components/job-detail", () => ({
  JobDetail: ({ jobId }: { jobId: string }) => <div role="region" aria-label={`Job ${jobId}`} />,
}));
vi.mock("@/features/admin-prompts/components/templates-table", () => ({
  TemplatesTable: () => <div role="region" aria-label="Templates table" />,
}));
vi.mock("@/features/admin-prompts/components/template-detail", () => ({
  TemplateDetail: ({ templateKey }: { templateKey: string }) => (
    <div role="region" aria-label={`Template ${templateKey}`} />
  ),
}));
vi.mock("@/features/admin-skills/components/skills-overview", () => ({
  SkillsOverview: () => <div role="region" aria-label="Skills overview" />,
}));
vi.mock("@/features/admin-skills/components/skill-detail", () => ({
  SkillDetail: ({ slug }: { slug: string }) => <div role="region" aria-label={`Skill ${slug}`} />,
}));
vi.mock("@/features/library/components/library-view", () => ({
  LibraryView: () => <div role="region" aria-label="Library view" />,
}));

const JOB_ID = "0197c5a2-1b2c-7d3e-8f40-5a6b7c8d9e01";

beforeEach(() => {
  vi.clearAllMocks();
});

describe("phase 9 pages", () => {
  it.each([
    ["/library", library.metadata, false],
    ["/admin/jobs", adminJobs.metadata, true],
    ["/admin/jobs", adminJob.metadata, true],
    ["/admin/prompts", adminPrompts.metadata, true],
    ["/admin/prompts", adminPromptTemplate.metadata, true],
    ["/admin/skills", adminSkills.metadata, true],
    ["/admin/skills", adminSkill.metadata, true],
  ])("%s is private and has a canonical url", (path, metadata) => {
    expect(metadata.robots).toEqual({ index: false, follow: false });
    expect(metadata.alternates?.canonical).toBe(`https://motionile.test${path}`);
    expect(metadata.description).toBeTruthy();
  });

  it("gives every page its own description", () => {
    const descriptions = [
      library,
      adminJobs,
      adminJob,
      adminPrompts,
      adminPromptTemplate,
      adminSkills,
      adminSkill,
    ].map((page) => page.metadata.description);

    expect(new Set(descriptions).size).toBe(descriptions.length);
  });

  it("renders the library with a link to create", () => {
    render(library.default());

    expect(screen.getByRole("heading", { level: 1, name: "Library" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Create video" })).toHaveAttribute("href", "/create");
    expect(screen.getByRole("region", { name: "Library view" })).toBeInTheDocument();
  });

  it("guards the jobs pages with jobs.read_all", async () => {
    render(await adminJobs.default());
    expect(requirePermissions).toHaveBeenLastCalledWith(["jobs.read_all"]);
    expect(screen.getByRole("region", { name: "Generation analytics" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Jobs table" })).toBeInTheDocument();

    render(await adminJob.default({ params: Promise.resolve({ jobId: JOB_ID }) }));
    expect(screen.getByRole("region", { name: `Job ${JOB_ID}` })).toBeInTheDocument();
    await expect(adminJob.default({ params: Promise.resolve({ jobId: "nope" }) })).rejects.toThrow(
      "NEXT_NOT_FOUND",
    );
  });

  it("guards the prompt pages with prompts.manage and rejects a malformed key", async () => {
    render(await adminPrompts.default());
    expect(requirePermissions).toHaveBeenLastCalledWith(["prompts.manage"]);

    render(
      await adminPromptTemplate.default({ params: Promise.resolve({ key: "planner.storyboard" }) }),
    );
    expect(screen.getByRole("region", { name: "Template planner.storyboard" })).toBeInTheDocument();
    await expect(
      adminPromptTemplate.default({ params: Promise.resolve({ key: "Bad Key" }) }),
    ).rejects.toThrow("NEXT_NOT_FOUND");
  });

  it("guards the skill pages with skills.manage and rejects a malformed slug", async () => {
    render(await adminSkills.default());
    expect(requirePermissions).toHaveBeenLastCalledWith(["skills.manage"]);

    render(await adminSkill.default({ params: Promise.resolve({ slug: "flow-diagram" }) }));
    expect(screen.getByRole("region", { name: "Skill flow-diagram" })).toBeInTheDocument();
    await expect(
      adminSkill.default({ params: Promise.resolve({ slug: "Bad Slug" }) }),
    ).rejects.toThrow("NEXT_NOT_FOUND");
  });
});

describe("phase 9 navigation", () => {
  it("lists the new admin areas behind their permissions", () => {
    const items = adminNavigation.items as readonly {
      title: string;
      href: string;
      permission: string;
    }[];

    expect(items.find((item) => item.href === "/admin/jobs")?.permission).toBe("jobs.read_all");
    expect(items.find((item) => item.href === "/admin/prompts")?.permission).toBe("prompts.manage");
    expect(items.find((item) => item.href === "/admin/skills")?.permission).toBe("skills.manage");
  });

  it("keeps shared video pages crawlable so each page decides on indexing", () => {
    const rules = robots().rules;
    const disallow = (Array.isArray(rules) ? rules[0] : rules)?.disallow ?? [];

    expect(crawlerDisallowedPaths.some((path) => "/v/abc".startsWith(path))).toBe(false);
    expect(disallow).not.toContain("/v");
    expect(disallow).not.toContain("/v/");
  });
});
