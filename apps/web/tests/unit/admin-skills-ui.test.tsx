import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NuqsTestingAdapter } from "nuqs/adapters/testing";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SkillDetail } from "@/features/admin-skills/components/skill-detail";
import { SkillsOverview } from "@/features/admin-skills/components/skills-overview";
import type {
  SystemSkill,
  SystemSkillDetail,
} from "@/features/admin-skills/types/admin-skills.types";
import { ApiError } from "@/lib/api/api-error";

import { renderWithQuery } from "./render-with-query";

const api = vi.hoisted(() => ({
  listSystemSkills: vi.fn(),
  getSystemSkill: vi.fn(),
  reseedSystemSkills: vi.fn(),
}));

vi.mock("@/features/admin-skills/api/admin-skills.api", () => api);

const withNuqs = (ui: ReactElement, searchParams = "") => (
  <NuqsTestingAdapter searchParams={searchParams}>{ui}</NuqsTestingAdapter>
);

const skill = (overrides: Partial<SystemSkill> = {}): SystemSkill => ({
  checksum: "0123456789abcdef0123456789abcdef",
  description: "Explains data flow with animated boxes and arrows.",
  embeddingStatus: "ready",
  layer: "visual",
  name: "Flow diagram",
  slug: "flow-diagram",
  tokenCount: 1850,
  updatedAt: "2026-10-20T09:00:00.000Z",
  version: 3,
  ...overrides,
});

const detail = (overrides: Partial<SystemSkillDetail> = {}): SystemSkillDetail => ({
  ...skill(),
  versions: [
    { checksum: "0123456789abcdef", createdAt: "2026-10-20T09:00:00.000Z", number: 3 },
    { checksum: "fedcba9876543210", createdAt: "2026-10-10T09:00:00.000Z", number: 2 },
  ],
  ...overrides,
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(600);
  vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(1200);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("system skills table", () => {
  it("lists skills with version, checksum prefix, tokens and embedding status", async () => {
    api.listSystemSkills.mockResolvedValue({
      items: [
        skill(),
        skill({ slug: "terminal", name: "Terminal", layer: "style", embeddingStatus: "stale" }),
      ],
      nextCursor: null,
    });
    renderWithQuery(withNuqs(<SkillsOverview />));

    const table = await screen.findByRole("table", { name: "System skills" });

    expect(within(table).getByRole("link", { name: "Flow diagram" })).toHaveAttribute(
      "href",
      "/admin/skills/flow-diagram",
    );
    expect(within(table).getAllByText("v3")).toHaveLength(2);
    expect(within(table).getAllByText("0123456789ab")).toHaveLength(2);
    expect(within(table).getAllByText("1,850")).toHaveLength(2);
    expect(within(table).getByText("Embedding ready")).toBeInTheDocument();
    expect(within(table).getByText("Embedding stale")).toBeInTheDocument();
  });

  it("filters by the layer in the url", async () => {
    api.listSystemSkills.mockResolvedValue({ items: [], nextCursor: null });
    renderWithQuery(withNuqs(<SkillsOverview />, "?layer=style"));

    await screen.findByText("No system skills match these filters.");

    expect(api.listSystemSkills).toHaveBeenCalledWith({ layer: "style" }, undefined);
    expect(screen.getByLabelText("Layer")).toHaveValue("style");
  });

  it("reseeds after confirmation and shows the report", async () => {
    api.listSystemSkills.mockResolvedValue({ items: [skill()], nextCursor: null });
    api.reseedSystemSkills.mockResolvedValue({
      created: 1,
      updated: 2,
      unchanged: 27,
      embedded: 3,
    });
    renderWithQuery(withNuqs(<SkillsOverview />));

    await userEvent.click(await screen.findByRole("button", { name: "Reseed" }));
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Reseed" }),
    );

    const report = await screen.findByRole("status", { name: "Reseed result" });
    expect(within(report).getByText("Created").nextSibling).toHaveTextContent("1");
    expect(within(report).getByText("Updated").nextSibling).toHaveTextContent("2");
    expect(within(report).getByText("Unchanged").nextSibling).toHaveTextContent("27");
    expect(within(report).getByText("Descriptions embedded").nextSibling).toHaveTextContent("3");
  });

  it("explains a reseed that failed because the embedding provider is down", async () => {
    api.listSystemSkills.mockResolvedValue({ items: [skill()], nextCursor: null });
    api.reseedSystemSkills.mockRejectedValue(
      new ApiError({
        kind: "http",
        status: 502,
        code: "skill_embedding_unavailable",
        title: "x",
        detail: null,
      }),
    );
    renderWithQuery(withNuqs(<SkillsOverview />));

    await userEvent.click(await screen.findByRole("button", { name: "Reseed" }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Reseed" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "embedding provider is unavailable",
    );
    expect(screen.queryByRole("status", { name: "Reseed result" })).not.toBeInTheDocument();
  });
});

describe("system skill detail", () => {
  it("shows metadata and the version history but never any skill text", async () => {
    api.getSystemSkill.mockResolvedValue(detail());
    renderWithQuery(<SkillDetail slug="flow-diagram" />);

    const history = await screen.findByRole("table", { name: "Versions of Flow diagram" });

    expect(within(history).getByText("v3 (current)")).toBeInTheDocument();
    expect(within(history).getByText("fedcba987654")).toBeInTheDocument();
    expect(screen.getByText(/System skill text is never returned/)).toBeInTheDocument();
  });

  it("explains a missing skill and retries", async () => {
    api.getSystemSkill
      .mockRejectedValueOnce(
        new ApiError({
          kind: "http",
          status: 404,
          code: "skill_not_found",
          title: "x",
          detail: null,
        }),
      )
      .mockResolvedValueOnce(detail());
    renderWithQuery(<SkillDetail slug="flow-diagram" />);

    expect(await screen.findByRole("alert")).toHaveTextContent("does not exist");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));

    await waitFor(() => {
      expect(screen.getByRole("table", { name: "Versions of Flow diagram" })).toBeInTheDocument();
    });
  });
});
