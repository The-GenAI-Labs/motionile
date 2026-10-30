import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { LibraryPlayer } from "@/features/library/components/library-player";
import { columnsForWidth } from "@/features/library/hooks/use-column-count";
import { ApiError } from "@/lib/api/api-error";

import { presignedSession } from "./library-fixtures";
import { libraryItem } from "./library-list-fixtures";
import { renderWithQuery } from "./render-with-query";

const api = vi.hoisted(() => ({ getMediaSession: vi.fn() }));
const player = vi.hoisted(() => ({ onPlaybackError: undefined as undefined | (() => void) }));

vi.mock("@/features/library/api/library.api", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  ...api,
}));
vi.mock("@/features/library/components/lazy-video-player", () => ({
  LazyVideoPlayer: (props: {
    title: string;
    deliveryMode: string;
    renditions: unknown[];
    onPlaybackError: () => void;
  }) => {
    player.onPlaybackError = props.onPlaybackError;
    return (
      <video
        aria-label={props.title}
        data-mode={props.deliveryMode}
        data-renditions={props.renditions.length}
      />
    );
  },
}));

describe("library player", () => {
  it("plays the renditions of the item once the viewing session is ready", async () => {
    api.getMediaSession.mockResolvedValue(presignedSession);
    renderWithQuery(<LibraryPlayer item={libraryItem()} onRefreshRenditions={vi.fn()} />);

    const video = await screen.findByLabelText("How DNS works");

    expect(video).toHaveAttribute("data-mode", "presigned");
    expect(video).toHaveAttribute("data-renditions", "2");
  });

  it("reloads the library when playback fails", async () => {
    api.getMediaSession.mockResolvedValue(presignedSession);
    const onRefreshRenditions = vi.fn();
    renderWithQuery(
      <LibraryPlayer item={libraryItem()} onRefreshRenditions={onRefreshRenditions} />,
    );
    await screen.findByLabelText("How DNS works");

    player.onPlaybackError?.();

    expect(onRefreshRenditions).toHaveBeenCalledTimes(1);
  });

  it("offers a retry when the session cannot start", async () => {
    api.getMediaSession.mockRejectedValue(
      new ApiError({
        kind: "http",
        status: 401,
        code: "unauthenticated",
        title: "x",
        detail: null,
      }),
    );
    renderWithQuery(<LibraryPlayer item={libraryItem()} onRefreshRenditions={vi.fn()} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("viewing session");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
  });
});

describe("grid columns", () => {
  it.each([
    [0, 1],
    [599, 1],
    [600, 2],
    [960, 3],
    [1280, 4],
    [2000, 4],
  ])("uses the right number of columns for %i px", (width, columns) => {
    expect(columnsForWidth(width)).toBe(columns);
  });
});
