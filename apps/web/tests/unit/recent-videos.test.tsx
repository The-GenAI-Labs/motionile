import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { RecentVideos } from "@/features/library/components/recent-videos";
import { ApiError } from "@/lib/api/api-error";

import { activeJob, jobId, libraryItem } from "./library-list-fixtures";
import { renderWithQuery } from "./render-with-query";

const library = vi.hoisted(() => ({ listLibrary: vi.fn() }));
const generation = vi.hoisted(() => ({ listJobs: vi.fn() }));

vi.mock("@/features/library/api/library.api", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  ...library,
}));
vi.mock("@/features/generation/api/generation.api", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  ...generation,
}));

describe("recent videos", () => {
  it("lists the latest finished videos as links to their jobs", async () => {
    library.listLibrary.mockResolvedValue({
      items: [
        libraryItem({ jobId: jobId(1), title: "How DNS works" }),
        libraryItem({ jobId: jobId(2), title: "What is TLS" }),
      ],
      nextCursor: null,
    });
    generation.listJobs.mockResolvedValue({ items: [], nextCursor: null });
    renderWithQuery(<RecentVideos />);

    const list = await screen.findByRole("list", { name: "Recent videos" });

    expect(within(list).getByRole("link", { name: /How DNS works/ })).toHaveAttribute(
      "href",
      `/jobs/${jobId(1)}`,
    );
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    expect(library.listLibrary).toHaveBeenCalledWith({}, undefined, 6);
    expect(screen.getByRole("link", { name: "View library" })).toHaveAttribute("href", "/library");
  });

  it("shows jobs in progress with their status and hides finished jobs", async () => {
    library.listLibrary.mockResolvedValue({ items: [], nextCursor: null });
    generation.listJobs.mockResolvedValue({
      items: [
        activeJob(),
        activeJob({ id: jobId(5), query: "Old finished topic", status: "completed" }),
      ],
      nextCursor: null,
    });
    renderWithQuery(<RecentVideos />);

    const list = await screen.findByRole("list", { name: "Videos in progress" });

    expect(within(list).getAllByRole("listitem")).toHaveLength(1);
    expect(within(list).getByRole("link", { name: /Explain TCP handshakes/ })).toHaveAttribute(
      "href",
      "/jobs/0197c5a2-1b2c-7d3e-8f40-5a6b7c8db001",
    );
    expect(within(list).getByText("Recording narration")).toBeInTheDocument();
  });

  it("invites the user to create a first video when there is nothing yet", async () => {
    library.listLibrary.mockResolvedValue({ items: [], nextCursor: null });
    generation.listJobs.mockResolvedValue({ items: [], nextCursor: null });
    renderWithQuery(<RecentVideos />);

    expect(await screen.findByRole("link", { name: "Create your first video" })).toHaveAttribute(
      "href",
      "/create",
    );
  });

  it("reports a failure and retries", async () => {
    library.listLibrary
      .mockRejectedValueOnce(
        new ApiError({
          kind: "http",
          status: 503,
          code: "service_unavailable",
          title: "x",
          detail: null,
        }),
      )
      .mockResolvedValueOnce({ items: [libraryItem({ title: "Recovered" })], nextCursor: null });
    generation.listJobs.mockResolvedValue({ items: [], nextCursor: null });
    renderWithQuery(<RecentVideos />);

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("link", { name: /Recovered/ })).toBeInTheDocument();
  });

  it("shows a loading state first", () => {
    library.listLibrary.mockReturnValue(new Promise(() => undefined));
    generation.listJobs.mockReturnValue(new Promise(() => undefined));
    renderWithQuery(<RecentVideos />);

    expect(screen.getByRole("status", { name: "Loading recent videos" })).toBeInTheDocument();
  });
});
