import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { VideoPlayer } from "@/features/library/components/video-player";
import type { Rendition } from "@/features/library/types/library.types";

import { landscape, portrait, rendition, square } from "./library-fixtures";

const playSpy = vi.fn(() => Promise.resolve());
const loadSpy = vi.fn();
let paused = true;

beforeEach(() => {
  paused = true;
  vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(playSpy);
  vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(loadSpy);
  vi.spyOn(HTMLMediaElement.prototype, "paused", "get").mockImplementation(() => paused);
  vi.spyOn(HTMLMediaElement.prototype, "readyState", "get").mockReturnValue(4);
});

afterEach(() => {
  vi.restoreAllMocks();
  playSpy.mockClear();
  loadSpy.mockClear();
});

const renderPlayer = (
  props: Partial<React.ComponentProps<typeof VideoPlayer>> & { renditions?: Rendition[] } = {},
) =>
  render(
    <VideoPlayer
      renditions={[landscape, portrait, square]}
      deliveryMode="cloudfront"
      title="Explainer video"
      {...props}
    />,
  );

const video = (): HTMLVideoElement =>
  screen.getByLabelText("Explainer video", { selector: "video" });

describe("VideoPlayer element", () => {
  it("renders a native video with a poster, metadata preload and no autoplay", () => {
    renderPlayer();

    expect(video()).toHaveAttribute("src", landscape.url);
    expect(video()).toHaveAttribute("poster", landscape.posterUrl);
    expect(video()).toHaveAttribute("preload", "metadata");
    expect(video().controls).toBe(true);
    expect(video().hasAttribute("playsinline")).toBe(true);
    expect(video().autoplay).toBe(false);
  });

  it("points a captions track at the WebVTT file", () => {
    renderPlayer();

    const track = video().querySelector("track");
    expect(track).toHaveAttribute("kind", "captions");
    expect(track).toHaveAttribute("src", landscape.subtitlesUrl);
    expect(track).toHaveAttribute("label", "Captions");
  });

  it("omits the captions track when subtitles are burned in or missing", () => {
    const { rerender } = renderPlayer({
      renditions: [rendition({ burnedInSubtitles: true })],
    });
    expect(video().querySelector("track")).toBeNull();

    rerender(
      <VideoPlayer
        renditions={[rendition({ subtitlesUrl: null })]}
        deliveryMode="cloudfront"
        title="Explainer video"
      />,
    );
    expect(video().querySelector("track")).toBeNull();
  });

  it("sends cookies in cloudfront mode and stays anonymous when presigned", () => {
    const { unmount } = renderPlayer({ deliveryMode: "cloudfront" });
    expect(video().getAttribute("crossorigin")).toBe("use-credentials");
    unmount();

    renderPlayer({ deliveryMode: "presigned" });
    expect(video().getAttribute("crossorigin")).toBe("anonymous");
  });

  it("falls back to the jpeg poster and ignores renditions that are not ready", () => {
    renderPlayer({
      renditions: [
        rendition({ posterUrl: null, posterJpegUrl: "https://cdn.motionile.test/p.jpg" }),
        { ...portrait, status: "rendering" },
        { ...square, url: null },
      ],
    });

    expect(video()).toHaveAttribute("poster", "https://cdn.motionile.test/p.jpg");
    expect(screen.queryByRole("radiogroup")).toBeNull();
  });

  it("explains when nothing is playable", () => {
    renderPlayer({ renditions: [{ ...landscape, status: "pending", url: null }] });

    expect(screen.getByRole("heading", { name: "No playable video yet" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Explainer video", { selector: "video" })).toBeNull();
  });

  it("shows a loading status until the metadata arrives", () => {
    renderPlayer();

    expect(screen.getByRole("status")).toHaveTextContent("Loading video");
    fireEvent.loadedMetadata(video());
    expect(screen.queryByRole("status")).toBeNull();
  });
});

describe("VideoPlayer aspect switcher", () => {
  it("is a labelled radio group of the available renditions", () => {
    renderPlayer();

    const group = screen.getByRole("radiogroup", { name: "Aspect ratio" });
    expect(group).toBeInTheDocument();
    const radios = screen.getAllByRole("radio");
    expect(radios.map((radio) => radio.getAttribute("aria-label"))).toEqual([
      "16:9 landscape",
      "9:16 portrait",
      "1:1 square",
    ]);
    expect(screen.getByRole("radio", { name: "16:9 landscape" })).toBeChecked();
  });

  it("orders renditions by aspect and hides the switcher for a single rendition", () => {
    const { unmount } = renderPlayer({ renditions: [square, portrait, landscape] });
    expect(screen.getAllByRole("radio").map((radio) => (radio as HTMLInputElement).value)).toEqual([
      "16:9",
      "9:16",
      "1:1",
    ]);
    unmount();

    renderPlayer({ renditions: [portrait] });
    expect(screen.queryByRole("radiogroup")).toBeNull();
    expect(video()).toHaveAttribute("src", portrait.url);
  });

  it("starts on the requested aspect", () => {
    renderPlayer({ initialAspect: "9:16" });

    expect(video()).toHaveAttribute("src", portrait.url);
    expect(screen.getByRole("radio", { name: "9:16 portrait" })).toBeChecked();
  });

  it("switches with a click", async () => {
    const user = userEvent.setup();
    renderPlayer();

    await user.click(screen.getByRole("radio", { name: "1:1 square" }));

    expect(video()).toHaveAttribute("src", square.url);
    expect(screen.getByRole("radio", { name: "1:1 square" })).toBeChecked();
  });

  it("switches with the arrow keys and keeps focus visible on the radio", async () => {
    const user = userEvent.setup();
    renderPlayer();

    await user.tab();
    const first = screen.getByRole("radio", { name: "16:9 landscape" });
    await user.click(first);
    first.focus();
    expect(first).toHaveFocus();

    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("radio", { name: "9:16 portrait" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "9:16 portrait" })).toHaveFocus();
    expect(video()).toHaveAttribute("src", portrait.url);

    await user.keyboard("{ArrowRight}");
    expect(video()).toHaveAttribute("src", square.url);

    await user.keyboard("{ArrowLeft}");
    expect(video()).toHaveAttribute("src", portrait.url);
  });

  it("keeps the playback position when switching", async () => {
    const user = userEvent.setup();
    renderPlayer();
    video().currentTime = 12;

    await user.click(screen.getByRole("radio", { name: "9:16 portrait" }));
    fireEvent.loadedMetadata(video());

    expect(video().currentTime).toBe(12);
    expect(playSpy).not.toHaveBeenCalled();
  });

  it("resumes playback after switching while playing", async () => {
    const user = userEvent.setup();
    renderPlayer();
    video().currentTime = 7;
    paused = false;
    fireEvent.play(video());

    await user.click(screen.getByRole("radio", { name: "1:1 square" }));
    paused = true;
    fireEvent.loadedMetadata(video());

    expect(video().currentTime).toBe(7);
    expect(playSpy).toHaveBeenCalledTimes(1);
  });
});

describe("VideoPlayer URL refresh", () => {
  const refreshed = (url: string): Rendition[] => [{ ...landscape, url }, portrait];

  it("applies refreshed urls straight away while paused", () => {
    const { rerender } = renderPlayer();

    rerender(
      <VideoPlayer
        renditions={refreshed("https://storage.motionile.test/new.mp4")}
        deliveryMode="presigned"
        title="Explainer video"
      />,
    );

    expect(video()).toHaveAttribute("src", "https://storage.motionile.test/new.mp4");
  });

  it("waits for a pause before swapping the url of a playing video", () => {
    const { rerender } = renderPlayer();
    fireEvent.play(video());

    rerender(
      <VideoPlayer
        renditions={refreshed("https://storage.motionile.test/new.mp4")}
        deliveryMode="presigned"
        title="Explainer video"
      />,
    );
    expect(video()).toHaveAttribute("src", landscape.url);

    fireEvent.pause(video());
    expect(video()).toHaveAttribute("src", "https://storage.motionile.test/new.mp4");
  });

  it("restores the position after a refreshed url loads", () => {
    const { rerender } = renderPlayer();
    video().currentTime = 21;
    fireEvent.timeUpdate(video());

    rerender(
      <VideoPlayer
        renditions={refreshed("https://storage.motionile.test/new.mp4")}
        deliveryMode="presigned"
        title="Explainer video"
      />,
    );
    video().currentTime = 0;
    vi.spyOn(HTMLMediaElement.prototype, "readyState", "get").mockReturnValue(0);
    fireEvent.timeUpdate(video());
    fireEvent.loadedMetadata(video());

    expect(video().currentTime).toBe(21);
  });
});

describe("VideoPlayer errors", () => {
  it("shows the error state, notifies the owner and retries on demand", async () => {
    const user = userEvent.setup();
    const onPlaybackError = vi.fn();
    renderPlayer({ onPlaybackError });

    fireEvent.error(video());

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("This video could not be played");
    expect(onPlaybackError).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Try again" }));

    expect(loadSpy).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("applies a refreshed url after an error and resumes where it stopped", () => {
    const { rerender } = renderPlayer();
    video().currentTime = 30;
    paused = false;
    fireEvent.play(video());

    fireEvent.error(video());
    rerender(
      <VideoPlayer
        renditions={[{ ...landscape, url: "https://storage.motionile.test/new.mp4" }, portrait]}
        deliveryMode="presigned"
        title="Explainer video"
      />,
    );

    expect(video()).toHaveAttribute("src", "https://storage.motionile.test/new.mp4");
    fireEvent.loadedMetadata(video());
    expect(video().currentTime).toBe(30);
    expect(playSpy).toHaveBeenCalledTimes(1);
  });

  it("can focus the retry button with the keyboard", async () => {
    const user = userEvent.setup();
    renderPlayer();
    fireEvent.error(video());

    const retry = screen.getByRole("button", { name: "Try again" });
    retry.focus();
    expect(retry).toHaveFocus();
    await user.keyboard("{Enter}");

    expect(loadSpy).toHaveBeenCalledTimes(1);
  });
});

describe("VideoPlayer music credit", () => {
  const attribution = {
    trackId: "0197c5a2-1b2c-7d3e-8f40-5a6b7c8d9e20",
    title: "Quiet Orbit",
    licenseName: "CC BY 4.0",
    licenseUrl: "https://creativecommons.org/licenses/by/4.0/",
    attributionText: "Composed by Ada",
  };

  it("credits the music with a link to the license", () => {
    renderPlayer({ renditions: [rendition({ attribution })] });

    expect(screen.getByText("Quiet Orbit")).toBeInTheDocument();
    expect(screen.getByText(/Composed by Ada/)).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "CC BY 4.0" });
    expect(link).toHaveAttribute("href", attribution.licenseUrl);
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("shows no link for a license url that is not https", () => {
    renderPlayer({
      renditions: [
        rendition({ attribution: { ...attribution, licenseUrl: "javascript:alert(1)" } }),
      ],
    });

    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByText(/CC BY 4.0/)).toBeInTheDocument();
  });

  it("shows no credit without attribution", () => {
    renderPlayer();

    expect(screen.queryByText(/Music:/)).toBeNull();
  });
});
