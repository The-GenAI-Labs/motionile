import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NuqsTestingAdapter, type OnUrlUpdateFunction } from "nuqs/adapters/testing";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LibraryView } from "@/features/library/components/library-view";
import { ApiError } from "@/lib/api/api-error";

import { jobId, libraryItem } from "./library-list-fixtures";
import { renderWithQuery } from "./render-with-query";

const library = vi.hoisted(() => ({ listLibrary: vi.fn() }));
const generation = vi.hoisted(() => ({
  deleteJob: vi.fn(),
  createShareLink: vi.fn(),
  revokeShareLinks: vi.fn(),
  listJobs: vi.fn(),
}));

vi.mock("@/features/library/api/library.api", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  ...library,
}));
vi.mock("@/features/generation/api/generation.api", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  ...generation,
}));
vi.mock("@/features/library/components/library-player", () => ({
  LibraryPlayer: ({ item }: { item: { title: string } }) => (
    <div role="region" aria-label={`Player for ${item.title}`} />
  ),
}));

const withNuqs = (ui: ReactElement, searchParams = "") => (
  <NuqsTestingAdapter searchParams={searchParams}>{ui}</NuqsTestingAdapter>
);

const problem = (code: string, status: number) =>
  new ApiError({ kind: "http", status, code, title: code, detail: null });

const page = (count: number, nextCursor: string | null = null) => ({
  items: Array.from({ length: count }, (_, index) =>
    libraryItem({ jobId: jobId(index + 1), title: `Video ${String(index + 1)}` }),
  ),
  nextCursor,
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(700);
  vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(1300);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("library view", () => {
  it("renders only a window of a long list", async () => {
    library.listLibrary.mockResolvedValue(page(100, "next"));
    renderWithQuery(withNuqs(<LibraryView />));

    const grid = await screen.findByRole("region", { name: "Your videos" });
    const cards = within(grid).getAllByRole("listitem");

    expect(cards.length).toBeGreaterThanOrEqual(4);
    expect(cards.length).toBeLessThan(40);
    expect(within(grid).getByRole("button", { name: "Play Video 1" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Play Video 100" })).not.toBeInTheDocument();
  });

  it("shows the fallback notice, aspects and shared state of a video", async () => {
    library.listLibrary.mockResolvedValue({
      items: [libraryItem({ fallbackSceneIds: ["a", "b"], shareSlug: "abc" })],
      nextCursor: null,
    });
    renderWithQuery(withNuqs(<LibraryView />));

    expect(await screen.findByText("2 scenes use a simplified layout")).toBeInTheDocument();
    expect(screen.getByText("Shared")).toBeInTheDocument();
    expect(screen.getByText("16:9")).toBeInTheDocument();
    expect(screen.getByText("1:02")).toBeInTheDocument();
  });

  it("loads the next page from the load more button", async () => {
    library.listLibrary
      .mockResolvedValueOnce(page(2, "cursor-2"))
      .mockResolvedValueOnce({ items: [libraryItem({ jobId: jobId(9), title: "Video 9" })] });
    renderWithQuery(withNuqs(<LibraryView />));

    await userEvent.click(await screen.findByRole("button", { name: "Load more videos" }));

    expect(await screen.findByRole("button", { name: "Play Video 9" })).toBeInTheDocument();
    expect(library.listLibrary).toHaveBeenLastCalledWith({}, "cursor-2");
  });

  it("sends the search text and aspect from the url to the library", async () => {
    library.listLibrary.mockResolvedValue(page(1));
    renderWithQuery(withNuqs(<LibraryView />, "?q=dns&aspect=9:16"));

    expect(screen.getByRole("searchbox", { name: "Search videos" })).toHaveValue("dns");
    expect(screen.getByLabelText("Aspect ratio")).toHaveValue("9:16");
    await waitFor(() => {
      expect(library.listLibrary.mock.calls.at(-1)).toEqual([
        { q: "dns", aspect: "9:16" },
        undefined,
      ]);
    });
  });

  it("writes the search text and aspect to the url", async () => {
    library.listLibrary.mockResolvedValue(page(1));
    const onUrlUpdate = vi.fn<OnUrlUpdateFunction>();
    renderWithQuery(
      <NuqsTestingAdapter onUrlUpdate={onUrlUpdate}>
        <LibraryView />
      </NuqsTestingAdapter>,
    );
    await screen.findByRole("button", { name: "Play Video 1" });

    await userEvent.selectOptions(screen.getByLabelText("Aspect ratio"), "1:1");
    await userEvent.type(screen.getByRole("searchbox", { name: "Search videos" }), "d");

    await waitFor(() => {
      expect(onUrlUpdate.mock.calls.map(([event]) => event.queryString)).toEqual(
        expect.arrayContaining(["?aspect=1:1", "?q=d"]),
      );
    });
  });

  it("explains an empty library and links to create", async () => {
    library.listLibrary.mockResolvedValue({ items: [], nextCursor: null });
    renderWithQuery(withNuqs(<LibraryView />));

    expect(await screen.findByRole("heading", { name: "No videos yet" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Create your first video" })).toHaveAttribute(
      "href",
      "/create",
    );
  });

  it("explains an empty result for the current filters", async () => {
    library.listLibrary.mockResolvedValue({ items: [], nextCursor: null });
    renderWithQuery(withNuqs(<LibraryView />, "?q=zzz"));

    expect(await screen.findByRole("heading", { name: "No videos match" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Clear filters" })).toHaveLength(2);
  });

  it("reports a failed load and retries", async () => {
    library.listLibrary
      .mockRejectedValueOnce(problem("rate_limited", 429))
      .mockResolvedValueOnce(page(1));
    renderWithQuery(withNuqs(<LibraryView />));

    expect(await screen.findByRole("alert")).toHaveTextContent("Too many requests");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("button", { name: "Play Video 1" })).toBeInTheDocument();
  });

  it("opens a video in a dialog with its player and actions", async () => {
    library.listLibrary.mockResolvedValue(page(1));
    renderWithQuery(withNuqs(<LibraryView />));

    await userEvent.click(await screen.findByRole("button", { name: "Play Video 1" }));

    const dialog = await screen.findByRole("dialog", { name: "Video 1" });
    expect(within(dialog).getByRole("region", { name: "Player for Video 1" })).toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: "Revise Video 1" })).toHaveAttribute(
      "href",
      `/jobs/${jobId(1)}`,
    );
  });

  it("deletes a video after confirmation", async () => {
    library.listLibrary.mockResolvedValue(page(1));
    generation.deleteJob.mockResolvedValue(undefined);
    renderWithQuery(withNuqs(<LibraryView />));

    await userEvent.click(await screen.findByRole("button", { name: "Delete Video 1" }));
    const confirm = await screen.findByRole("alertdialog");
    await userEvent.click(within(confirm).getByRole("button", { name: "Delete video" }));

    await waitFor(() => {
      expect(generation.deleteJob).toHaveBeenCalledWith(jobId(1));
    });
  });

  it("shows why a delete failed", async () => {
    library.listLibrary.mockResolvedValue(page(1));
    generation.deleteJob.mockRejectedValue(problem("job_not_deletable", 409));
    renderWithQuery(withNuqs(<LibraryView />));

    await userEvent.click(await screen.findByRole("button", { name: "Delete Video 1" }));
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Delete video" }),
    );

    expect(await screen.findByText(/still being made cannot be deleted/)).toBeInTheDocument();
  });

  it("creates a share link for a chosen version and shows it", async () => {
    library.listLibrary.mockResolvedValue(page(1));
    generation.createShareLink.mockResolvedValue({
      allowIndexing: true,
      aspect: "9:16",
      createdAt: "2026-10-25T10:00:00.000Z",
      renditionId: "0197c5a2-1b2c-7d3e-8f40-5a6b7c8d9e11",
      slug: "abc123abc123",
      url: "https://motionile.test/v/abc123abc123",
      viewCount: 0,
    });
    renderWithQuery(withNuqs(<LibraryView />));

    await userEvent.click(await screen.findByRole("button", { name: "Share Video 1" }));
    const dialog = await screen.findByRole("dialog", { name: "Share this video" });
    await userEvent.selectOptions(within(dialog).getByLabelText("Version to share"), "9:16");
    await userEvent.click(within(dialog).getByRole("switch", { name: /index the page/ }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Create link" }));

    expect(await within(dialog).findByLabelText("Public link")).toHaveValue(
      "https://motionile.test/v/abc123abc123",
    );
    expect(generation.createShareLink).toHaveBeenCalledWith(jobId(1), {
      aspect: "9:16",
      allowIndexing: true,
    });
  });

  it("turns off sharing for an already shared video", async () => {
    library.listLibrary.mockResolvedValue({
      items: [libraryItem({ jobId: jobId(1), title: "Video 1", shareSlug: "abc123abc123" })],
      nextCursor: null,
    });
    generation.revokeShareLinks.mockResolvedValue(undefined);
    renderWithQuery(withNuqs(<LibraryView />));

    await userEvent.click(await screen.findByRole("button", { name: "Share Video 1" }));
    const dialog = await screen.findByRole("dialog", { name: "Share this video" });
    expect(within(dialog).getByLabelText("Public link")).toHaveValue(
      "https://motionile.test/v/abc123abc123",
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Turn off sharing" }));
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: "Turn off sharing",
      }),
    );

    await waitFor(() => {
      expect(generation.revokeShareLinks).toHaveBeenCalledWith(jobId(1));
    });
  });
});
