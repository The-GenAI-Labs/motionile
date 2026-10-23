import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { VoiceGallery } from "@/features/voices/components/voice-gallery";
import { ApiError } from "@/lib/api/api-error";

import { renderWithQuery } from "./render-with-query";
import { nth } from "./test-helpers";
import {
  clonedVoice,
  failedVoice,
  hindiVoice,
  pendingVoice,
  preferences,
  voice,
} from "./voices-fixtures";

const voicesApi = vi.hoisted(() => ({
  listVoices: vi.fn(),
  getVoicePreview: vi.fn(),
  deleteVoice: vi.fn(),
}));
const usersApi = vi.hoisted(() => ({
  userPreferences: vi.fn(),
  updateUserPreferences: vi.fn(),
}));

vi.mock("@/features/voices/api/voices.api", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  ...voicesApi,
}));
vi.mock("@/features/users/api/users.api", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  ...usersApi,
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const problem = (code: string, status: number) =>
  new ApiError({ kind: "http", status, code, title: code, detail: null });

const PREVIEW_URL = "http://localhost:9000/motionile/voice-preview/aria.mp3?X-Amz-Signature=abc";

const mediaState = { paused: true };

beforeEach(() => {
  vi.clearAllMocks();
  mediaState.paused = true;
  voicesApi.listVoices.mockResolvedValue({
    items: [voice(), hindiVoice, clonedVoice, pendingVoice, failedVoice],
    nextCursor: null,
  });
  voicesApi.getVoicePreview.mockResolvedValue({
    url: PREVIEW_URL,
    expiresAt: "2026-10-20T10:15:00Z",
  });
  usersApi.userPreferences.mockResolvedValue(preferences);
  usersApi.updateUserPreferences.mockImplementation((input: object) =>
    Promise.resolve({ ...preferences, ...input }),
  );
  vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(function play(
    this: HTMLMediaElement,
  ) {
    mediaState.paused = false;
    Object.defineProperty(this, "paused", { value: false, configurable: true });
    this.dispatchEvent(new Event("play"));
    return Promise.resolve();
  });
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(function pause(
    this: HTMLMediaElement,
  ) {
    mediaState.paused = true;
    Object.defineProperty(this, "paused", { value: true, configurable: true });
    this.dispatchEvent(new Event("pause"));
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("voice gallery", () => {
  it("shows built-in voices as cards with their language and tags", async () => {
    renderWithQuery(<VoiceGallery />);

    const list = await screen.findByRole("list", { name: "Built-in voices" });
    const headings = within(list).getAllByRole("heading", { level: 3 });
    const first = nth(headings, 0).closest("li") as HTMLElement;

    expect(headings).toHaveLength(2);
    expect(within(first).getByRole("heading", { name: "Aria" })).toBeInTheDocument();
    expect(first).toHaveTextContent("English");
    expect(within(first).getByRole("list", { name: "Tags for Aria" })).toHaveTextContent(
      "warmfemale",
    );
    expect(screen.getByRole("heading", { level: 2, name: "Built-in voices" })).toBeInTheDocument();
  });

  it("filters the built-in voices by language", async () => {
    const user = userEvent.setup();
    renderWithQuery(<VoiceGallery />);
    await screen.findByRole("list", { name: "Built-in voices" });

    await user.selectOptions(screen.getByRole("combobox", { name: "Language" }), "hi");

    const list = screen.getByRole("list", { name: "Built-in voices" });
    expect(within(list).getAllByRole("heading", { level: 3 })).toHaveLength(1);
    expect(within(list).getByRole("heading", { name: "Kavya" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "My voice" })).toBeInTheDocument();
  });

  it("plays one preview at a time and announces the state", async () => {
    const user = userEvent.setup();
    renderWithQuery(<VoiceGallery />);

    await user.click(await screen.findByRole("button", { name: "Play preview of Aria" }));

    expect(
      await screen.findByRole("button", { name: "Pause preview of Aria" }),
    ).toBeInTheDocument();
    expect(voicesApi.getVoicePreview).toHaveBeenCalledWith(voice().id);
    expect(screen.getByText("Playing preview of Aria.")).toBeInTheDocument();
    expect(document.querySelector("audio")).toHaveAttribute("src", PREVIEW_URL);

    await user.click(screen.getByRole("button", { name: "Play preview of Kavya" }));

    expect(
      await screen.findByRole("button", { name: "Pause preview of Kavya" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Play preview of Aria" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /^Pause preview/ })).toHaveLength(1);
  });

  it("pauses the playing preview and says so", async () => {
    const user = userEvent.setup();
    renderWithQuery(<VoiceGallery />);

    await user.click(await screen.findByRole("button", { name: "Play preview of Aria" }));
    await user.click(await screen.findByRole("button", { name: "Pause preview of Aria" }));

    expect(await screen.findByRole("button", { name: "Play preview of Aria" })).toBeInTheDocument();
    expect(screen.getByText("Paused preview of Aria.")).toBeInTheDocument();
  });

  it("explains a preview that is not ready", async () => {
    voicesApi.getVoicePreview.mockRejectedValue(problem("voice_preview_not_ready", 404));
    const user = userEvent.setup();
    renderWithQuery(<VoiceGallery />);

    await user.click(await screen.findByRole("button", { name: "Play preview of Aria" }));

    const card = (await screen.findByRole("heading", { name: "Aria" })).closest(
      "li",
    ) as HTMLElement;
    expect(await within(card).findByRole("alert")).toHaveTextContent("not ready yet");
  });

  it("hides the preview button for voices without a preview", async () => {
    voicesApi.listVoices.mockResolvedValue({
      items: [voice({ hasPreview: false })],
      nextCursor: null,
    });
    renderWithQuery(<VoiceGallery />);

    await screen.findByRole("heading", { name: "Aria" });

    expect(screen.queryByRole("button", { name: /preview of Aria/ })).not.toBeInTheDocument();
  });
});

describe("cloned voices", () => {
  it("shows status badges, progress text and guidance for each status", async () => {
    renderWithQuery(<VoiceGallery />);

    const list = await screen.findByRole("list", { name: "Your cloned voices" });
    const items = within(list).getAllByRole("listitem");
    const [ready, pending, failed] = [nth(items, 0), nth(items, 1), nth(items, 2)];

    expect(ready).toHaveTextContent("Ready");
    expect(pending).toHaveTextContent("Creating");
    expect(within(pending).getByRole("status")).toHaveTextContent(
      "Creating this voice. This page updates when it is ready.",
    );
    expect(failed).toHaveTextContent("Failed");
    expect(within(failed).getByRole("alert")).toHaveTextContent(
      "did not match the consent sentence",
    );
    expect(screen.getByRole("link", { name: "Clone your voice" })).toHaveAttribute(
      "href",
      "/settings/voices/new",
    );
  });

  it("tells the user a refused clone can simply be tried again", async () => {
    voicesApi.listVoices.mockResolvedValue({
      items: [{ ...failedVoice, failureCode: "credit_reservation_expired" }],
      nextCursor: null,
    });
    renderWithQuery(<VoiceGallery />);

    const card = (await screen.findByRole("heading", { name: "Broken" })).closest(
      "li",
    ) as HTMLElement;

    expect(within(card).getByRole("alert")).toHaveTextContent(
      "No credits were taken. Start again.",
    );
  });

  it("polls until a pending voice is ready", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    voicesApi.listVoices
      .mockResolvedValueOnce({ items: [pendingVoice], nextCursor: null })
      .mockResolvedValue({
        items: [{ ...pendingVoice, status: "ready", hasPreview: true }],
        nextCursor: null,
      });
    renderWithQuery(<VoiceGallery />);

    expect(
      await screen.findByText("Creating this voice. This page updates when it is ready."),
    ).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4_100);
    });

    await waitFor(() => {
      expect(
        screen.queryByText("Creating this voice. This page updates when it is ready."),
      ).not.toBeInTheDocument();
    });
    expect(voicesApi.listVoices).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("button", { name: "Play preview of Brewing" })).toBeInTheDocument();
  });

  it("shows the empty state before any clone exists", async () => {
    voicesApi.listVoices.mockResolvedValue({ items: [voice()], nextCursor: null });
    renderWithQuery(<VoiceGallery />);

    expect(
      await screen.findByRole("heading", { name: "No cloned voices yet" }),
    ).toBeInTheDocument();
  });
});

describe("default voice", () => {
  it("sets a voice as default through the preferences update and shows it", async () => {
    const user = userEvent.setup();
    renderWithQuery(<VoiceGallery />);

    expect(await screen.findByText(/No default voice/)).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Set Aria as default" }));

    await waitFor(() => {
      expect(usersApi.updateUserPreferences).toHaveBeenCalledTimes(1);
    });
    expect(usersApi.updateUserPreferences.mock.calls[0]?.[0]).toEqual({
      defaultStyle: null,
      pace: "normal",
      language: "en",
      depth: "standard",
      defaultAspect: "16:9",
      captionsEnabled: true,
      defaultVoiceId: voice().id,
    });
    expect(await screen.findByText("Your default voice is Aria.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Aria is your default voice" })).toBeDisabled();
    const card = screen.getByRole("heading", { name: "Aria" }).closest("li") as HTMLElement;
    expect(within(card).getAllByText("Default")).toHaveLength(2);
  });

  it("clears the default voice", async () => {
    usersApi.userPreferences.mockResolvedValue({ ...preferences, defaultVoiceId: voice().id });
    const user = userEvent.setup();
    renderWithQuery(<VoiceGallery />);

    expect(await screen.findByText("Your default voice is Aria.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear default voice" }));

    await waitFor(() => {
      expect(usersApi.updateUserPreferences).toHaveBeenCalledTimes(1);
    });
    expect(usersApi.updateUserPreferences.mock.calls[0]?.[0]).toMatchObject({
      defaultVoiceId: null,
    });
    expect(await screen.findByText(/No default voice/)).toBeInTheDocument();
  });

  it("explains when a voice cannot be the default", async () => {
    usersApi.updateUserPreferences.mockRejectedValue(problem("voice_not_available", 422));
    const user = userEvent.setup();
    renderWithQuery(<VoiceGallery />);

    await user.click(await screen.findByRole("button", { name: "Set Aria as default" }));

    expect(
      await within(screen.getByRole("region", { name: "Default voice" })).findByRole("alert"),
    ).toHaveTextContent("not available to select");
  });

  it("does not offer a default button for voices that are not ready", async () => {
    renderWithQuery(<VoiceGallery />);
    await screen.findByRole("heading", { name: "Brewing" });

    expect(
      screen.queryByRole("button", { name: "Set Brewing as default" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Set Broken as default" })).not.toBeInTheDocument();
  });
});

describe("deleting a cloned voice", () => {
  it("confirms before deleting and then deletes", async () => {
    voicesApi.deleteVoice.mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderWithQuery(<VoiceGallery />);

    await user.click(await screen.findByRole("button", { name: "Delete My voice" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Delete My voice?" });
    expect(voicesApi.deleteVoice).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "Delete voice" }));

    await waitFor(() => {
      expect(voicesApi.deleteVoice).toHaveBeenCalledWith(clonedVoice.id);
    });
  });

  it("keeps the dialog open and explains a busy voice", async () => {
    voicesApi.deleteVoice.mockRejectedValue(problem("voice_busy", 409));
    const user = userEvent.setup();
    renderWithQuery(<VoiceGallery />);

    await user.click(await screen.findByRole("button", { name: "Delete Brewing" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete voice" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent("still being created");
  });

  it("keeps the voice when the provider is unavailable", async () => {
    voicesApi.deleteVoice.mockRejectedValue(problem("voice_provider_unavailable", 502));
    const user = userEvent.setup();
    renderWithQuery(<VoiceGallery />);

    await user.click(await screen.findByRole("button", { name: "Delete My voice" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete voice" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent("voice was kept");
  });
});

describe("gallery loading and errors", () => {
  it("shows a loading state and then an error with retry", async () => {
    voicesApi.listVoices.mockRejectedValueOnce(problem("forbidden", 403));
    const user = userEvent.setup();
    renderWithQuery(<VoiceGallery />);

    expect(screen.getByRole("status")).toHaveTextContent("Loading voices");
    expect(await screen.findByRole("alert")).toHaveTextContent("not allowed");
    await user.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("list", { name: "Built-in voices" })).toBeInTheDocument();
  });

  it("loads every page of voices", async () => {
    voicesApi.listVoices
      .mockResolvedValueOnce({ items: [voice()], nextCursor: "next" })
      .mockResolvedValueOnce({ items: [hindiVoice], nextCursor: null });
    renderWithQuery(<VoiceGallery />);

    expect(await screen.findByRole("heading", { name: "Kavya" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Aria" })).toBeInTheDocument();
    expect(voicesApi.listVoices).toHaveBeenLastCalledWith({}, "next");
  });
});
