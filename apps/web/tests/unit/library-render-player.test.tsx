import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RenderPlayer } from "@/features/library/components/render-player";
import { ApiError } from "@/lib/api/api-error";

import {
  cloudfrontSession,
  landscape,
  portrait,
  presignedSession,
  RENDER_ID,
} from "./library-fixtures";
import { renderWithQuery } from "./render-with-query";

const api = vi.hoisted(() => ({
  getMediaSession: vi.fn(),
  getRender: vi.fn(),
  listRenditions: vi.fn(),
}));

vi.mock("@/features/library/api/library.api", () => api);

const SESSION_EXPIRY = "2099-01-01T00:00:00.000Z";

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
});

describe("RenderPlayer", () => {
  it("loads the session and the renditions, then plays with cookies in cloudfront mode", async () => {
    api.getMediaSession.mockResolvedValue(cloudfrontSession(SESSION_EXPIRY));
    api.listRenditions.mockResolvedValue({ items: [landscape, portrait] });
    renderWithQuery(<RenderPlayer renderId={RENDER_ID} title="Test render" />);

    expect(screen.getByRole("status")).toHaveTextContent("Loading video");
    const video = await screen.findByLabelText("Test render", { selector: "video" });

    expect(video).toHaveAttribute("src", landscape.url);
    expect(video.getAttribute("crossorigin")).toBe("use-credentials");
    expect(screen.getByRole("radiogroup", { name: "Aspect ratio" })).toBeInTheDocument();
    expect(api.listRenditions).toHaveBeenCalledWith(RENDER_ID);
  });

  it("plays anonymously in presigned mode", async () => {
    api.getMediaSession.mockResolvedValue(presignedSession);
    api.listRenditions.mockResolvedValue({ items: [landscape] });
    renderWithQuery(<RenderPlayer renderId={RENDER_ID} />);

    const video = await screen.findByLabelText("Video", { selector: "video" });

    expect(video.getAttribute("crossorigin")).toBe("anonymous");
  });

  it("shows an empty state when no rendition is ready", async () => {
    api.getMediaSession.mockResolvedValue(presignedSession);
    api.listRenditions.mockResolvedValue({ items: [] });
    renderWithQuery(<RenderPlayer renderId={RENDER_ID} />);

    expect(await screen.findByRole("heading", { name: "No playable video yet" })).toBeVisible();
  });

  it("reports a failed rendition list and retries", async () => {
    const user = userEvent.setup();
    api.getMediaSession.mockResolvedValue(presignedSession);
    api.listRenditions.mockRejectedValueOnce(
      new ApiError({
        kind: "http",
        status: 404,
        code: "render_not_found",
        title: "Render not found",
        detail: null,
      }),
    );
    api.listRenditions.mockResolvedValue({ items: [landscape] });
    renderWithQuery(<RenderPlayer renderId={RENDER_ID} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The video list could not be loaded.",
    );
    await user.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByLabelText("Video", { selector: "video" })).toBeInTheDocument();
  });

  it("reports a failed session start and retries", async () => {
    const user = userEvent.setup();
    api.getMediaSession.mockRejectedValueOnce(
      new ApiError({
        kind: "http",
        status: 503,
        code: "media_delivery_misconfigured",
        title: "Media delivery is not configured",
        detail: null,
      }),
    );
    api.getMediaSession.mockResolvedValue(presignedSession);
    api.listRenditions.mockResolvedValue({ items: [landscape] });
    renderWithQuery(<RenderPlayer renderId={RENDER_ID} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Your viewing session could not be started.",
    );
    await user.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByLabelText("Video", { selector: "video" })).toBeInTheDocument();
  });

  it("renews the session and the list after a playback error in cloudfront mode", async () => {
    api.getMediaSession.mockResolvedValue(cloudfrontSession(SESSION_EXPIRY));
    api.listRenditions.mockResolvedValue({ items: [landscape] });
    renderWithQuery(<RenderPlayer renderId={RENDER_ID} />);
    const video = await screen.findByLabelText("Video", { selector: "video" });

    fireEvent.error(video);

    await vi.waitFor(() => {
      expect(api.getMediaSession).toHaveBeenCalledTimes(2);
      expect(api.listRenditions).toHaveBeenCalledTimes(2);
    });
  });

  it("only re-fetches the list after a playback error in presigned mode", async () => {
    api.getMediaSession.mockResolvedValue(presignedSession);
    api.listRenditions.mockResolvedValue({ items: [landscape] });
    renderWithQuery(<RenderPlayer renderId={RENDER_ID} />);
    const video = await screen.findByLabelText("Video", { selector: "video" });

    fireEvent.error(video);

    await vi.waitFor(() => {
      expect(api.listRenditions).toHaveBeenCalledTimes(2);
    });
    expect(api.getMediaSession).toHaveBeenCalledTimes(1);
  });
});
