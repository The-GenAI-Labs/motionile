import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CursorPagination } from "@/components/shared/cursor-pagination";
import { createDataTableColumnHelper, DataTable } from "@/components/shared/data-table";

interface Video {
  id: string;
  title: string;
  durationSeconds: number;
}

const helper = createDataTableColumnHelper<Video>();
const columns = helper.columns([
  helper.accessor("title", { header: "Title" }),
  helper.accessor("durationSeconds", {
    header: "Duration",
    cell: (context) => `${String(context.getValue())} s`,
  }),
]);

const makeVideos = (count: number): Video[] =>
  Array.from({ length: count }, (_, index) => ({
    id: `video-${String(index)}`,
    title: `Video ${String(index)}`,
    durationSeconds: 10 + index,
  }));

const VIEWPORT_HEIGHT = 440;

beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(VIEWPORT_HEIGHT);
  vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(800);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("DataTable", () => {
  it("renders a captioned table with column headers and cells", () => {
    render(
      <DataTable
        caption="Your videos"
        columns={columns}
        data={makeVideos(3)}
        getRowId={(video) => video.id}
      />,
    );

    const table = screen.getByRole("table", { name: "Your videos" });
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((header) => header.textContent),
    ).toEqual(["Title", "Duration"]);
    expect(within(table).getByRole("cell", { name: "Video 1" })).toBeInTheDocument();
    expect(within(table).getByRole("cell", { name: "12 s" })).toBeInTheDocument();
    expect(table).toHaveAttribute("aria-rowcount", "4");
  });

  it("exposes a focusable scroll region for keyboard users", () => {
    render(
      <DataTable caption="Payments" columns={columns} data={[]} getRowId={(video) => video.id} />,
    );

    const region = screen.getByRole("region", { name: "Payments" });
    expect(region).toHaveAttribute("tabindex", "0");
  });

  it("renders only the visible window of a long list", () => {
    render(
      <DataTable
        caption="Many videos"
        columns={columns}
        data={makeVideos(1_000)}
        getRowId={(video) => video.id}
        estimateRowHeight={44}
      />,
    );

    const table = screen.getByRole("table", { name: "Many videos" });
    const dataRows = within(table)
      .getAllByRole("row")
      .filter((row) => row.hasAttribute("data-index"));
    expect(dataRows.length).toBeGreaterThan(0);
    expect(dataRows.length).toBeLessThan(50);
    expect(dataRows[0]).toHaveAttribute("aria-rowindex", "2");
    expect(within(table).queryByRole("cell", { name: "Video 999" })).not.toBeInTheDocument();
  });

  it("shows an empty state when there are no rows", () => {
    render(
      <DataTable
        caption="Refunds"
        columns={columns}
        data={[]}
        getRowId={(video) => video.id}
        emptyState="No refunds yet."
      />,
    );

    expect(screen.getByRole("cell", { name: "No refunds yet." })).toBeInTheDocument();
  });

  it("renders a footer such as cursor pagination", () => {
    render(
      <DataTable
        caption="Jobs"
        columns={columns}
        data={makeVideos(2)}
        getRowId={(video) => video.id}
        footer={<CursorPagination hasNextPage isFetchingNextPage={false} fetchNextPage={vi.fn()} />}
      />,
    );

    expect(screen.getByRole("button", { name: "Load more" })).toBeInTheDocument();
  });
});
