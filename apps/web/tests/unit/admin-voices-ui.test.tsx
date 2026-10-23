import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NuqsTestingAdapter } from "nuqs/adapters/testing";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EditVoiceDialog } from "@/features/admin-voices/components/edit-voice-dialog";
import { RegeneratePreviewButton } from "@/features/admin-voices/components/regenerate-preview-button";
import { SyncVoicesButton } from "@/features/admin-voices/components/sync-voices-button";
import { TagInput } from "@/features/admin-voices/components/tag-input";
import { VoicesTable } from "@/features/admin-voices/components/voices-table";
import { ApiError } from "@/lib/api/api-error";

import { renderWithQuery } from "./render-with-query";
import { adminVoice } from "./voices-fixtures";

const api = vi.hoisted(() => ({
  listAdminVoices: vi.fn(),
  syncVoices: vi.fn(),
  updateAdminVoice: vi.fn(),
  regenerateVoicePreview: vi.fn(),
}));
const voicesApi = vi.hoisted(() => ({ getVoicePreview: vi.fn() }));

vi.mock("@/features/admin-voices/api/admin-voices.api", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  ...api,
}));
vi.mock("@/features/voices/api/voices.api", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  ...voicesApi,
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const problem = (code: string, status: number) =>
  new ApiError({ kind: "http", status, code, title: code, detail: null });

const withNuqs = (ui: ReactElement, searchParams = "") => (
  <NuqsTestingAdapter hasMemory searchParams={searchParams}>
    {ui}
  </NuqsTestingAdapter>
);

const hidden = adminVoice({
  id: "0197c5a2-1b2c-7d3e-8f40-5a6b7c8d9c02",
  name: "Kavya",
  language: "hi",
  status: "disabled",
  hasPreview: false,
  tags: [],
  provider: "openai",
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(560);
  vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(1200);
  api.listAdminVoices.mockResolvedValue({ items: [adminVoice(), hidden], nextCursor: null });
  voicesApi.getVoicePreview.mockResolvedValue({
    url: "http://localhost:9000/voice-preview/aria.mp3?X-Amz-Signature=abc",
    expiresAt: "2026-10-20T10:15:00Z",
  });
  vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(function play(
    this: HTMLMediaElement,
  ) {
    Object.defineProperty(this, "paused", { value: false, configurable: true });
    this.dispatchEvent(new Event("play"));
    return Promise.resolve();
  });
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(function pause(
    this: HTMLMediaElement,
  ) {
    Object.defineProperty(this, "paused", { value: true, configurable: true });
    this.dispatchEvent(new Event("pause"));
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("voices table", () => {
  it("lists built-in voices with provider, language, tags, status and visibility", async () => {
    renderWithQuery(withNuqs(<VoicesTable />));

    const table = await screen.findByRole("table", { name: "Built-in voices" });

    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((header) => header.textContent),
    ).toEqual([
      "Name",
      "Provider",
      "Language",
      "Tags",
      "Status",
      "Visibility",
      "Preview",
      "Actions",
    ]);
    const aria = within(within(table).getByRole("row", { name: /Aria/ }));
    expect(aria.getByRole("cell", { name: "elevenlabs" })).toBeInTheDocument();
    expect(aria.getByRole("cell", { name: "English" })).toBeInTheDocument();
    expect(aria.getByRole("cell", { name: "warm, female" })).toBeInTheDocument();
    expect(aria.getByRole("cell", { name: "Ready" })).toBeInTheDocument();
    expect(aria.getByRole("cell", { name: "Exposed" })).toBeInTheDocument();
    const kavya = within(within(table).getByRole("row", { name: /Kavya/ }));
    expect(kavya.getByRole("cell", { name: "Disabled" })).toBeInTheDocument();
    expect(kavya.getByRole("cell", { name: "Hidden" })).toBeInTheDocument();
    expect(kavya.getByRole("cell", { name: "None" })).toBeInTheDocument();
    expect(kavya.getByRole("cell", { name: "Hindi" })).toBeInTheDocument();
  });

  it("filters by status and language", async () => {
    const user = userEvent.setup();
    renderWithQuery(withNuqs(<VoicesTable />));
    await screen.findByRole("table", { name: "Built-in voices" });

    await user.selectOptions(screen.getByRole("combobox", { name: "Status" }), "disabled");
    await waitFor(() => {
      expect(api.listAdminVoices).toHaveBeenLastCalledWith({ status: "disabled" }, undefined);
    });
    await user.selectOptions(screen.getByRole("combobox", { name: "Language" }), "hi");

    await waitFor(() => {
      expect(api.listAdminVoices).toHaveBeenLastCalledWith(
        { status: "disabled", language: "hi" },
        undefined,
      );
    });
  });

  it("plays the preview of an exposed voice inline and offers none for hidden ones", async () => {
    const user = userEvent.setup();
    renderWithQuery(withNuqs(<VoicesTable />));
    await screen.findByRole("table", { name: "Built-in voices" });

    await user.click(screen.getByRole("button", { name: "Play preview of Aria" }));

    expect(
      await screen.findByRole("button", { name: "Pause preview of Aria" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Play preview of Kavya" })).not.toBeInTheDocument();
    expect(screen.getByText("No preview")).toBeInTheDocument();
  });

  it("shows the empty and error states", async () => {
    api.listAdminVoices.mockResolvedValueOnce({ items: [], nextCursor: null });
    const { unmount } = renderWithQuery(withNuqs(<VoicesTable />));

    expect(await screen.findByText(/No built-in voices match these filters/)).toBeInTheDocument();
    unmount();
    api.listAdminVoices.mockRejectedValueOnce(problem("forbidden", 403));
    renderWithQuery(withNuqs(<VoicesTable />));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "not allowed to manage the voice catalog",
    );
  });
});

describe("sync from provider", () => {
  it("reports how many voices were added and unchanged", async () => {
    api.syncVoices.mockResolvedValue({ added: 3, unchanged: 12 });
    const user = userEvent.setup();
    renderWithQuery(<SyncVoicesButton />);

    await user.click(screen.getByRole("button", { name: "Sync from provider" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Sync finished: 3 voices added (hidden until exposed), 12 voices unchanged.",
    );
  });

  it("uses the singular for one voice and explains a provider outage", async () => {
    api.syncVoices.mockResolvedValueOnce({ added: 1, unchanged: 1 });
    const user = userEvent.setup();
    renderWithQuery(<SyncVoicesButton />);

    await user.click(screen.getByRole("button", { name: "Sync from provider" }));
    expect(await screen.findByRole("status")).toHaveTextContent("1 voice added");
    expect(screen.getByRole("status")).toHaveTextContent("1 voice unchanged");

    api.syncVoices.mockRejectedValueOnce(problem("voice_provider_unavailable", 502));
    await user.click(screen.getByRole("button", { name: "Sync from provider" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("provider is unavailable");
  });
});

describe("edit voice dialog", () => {
  it("edits name, language, tags and exposure and sends only the changes", async () => {
    api.updateAdminVoice.mockResolvedValue(adminVoice({ name: "Aria Two" }));
    const user = userEvent.setup();
    renderWithQuery(<EditVoiceDialog voice={hidden} />);

    await user.click(screen.getByRole("button", { name: "Edit Kavya" }));
    const dialog = await screen.findByRole("dialog", { name: "Edit voice" });
    const name = within(dialog).getByRole("textbox", { name: "Name" });
    await user.clear(name);
    await user.type(name, "Kavya Two");
    await user.type(within(dialog).getByRole("textbox", { name: "Tags" }), "  Calm {Enter}");
    await user.type(within(dialog).getByRole("textbox", { name: "Tags" }), "narrator{Enter}");
    await user.click(within(dialog).getByRole("button", { name: "Remove tag narrator" }));
    await user.click(within(dialog).getByRole("switch", { name: "Expose to users" }));

    expect(within(dialog).getByRole("status")).toHaveTextContent("generate a preview");
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));

    await waitFor(() => {
      expect(api.updateAdminVoice).toHaveBeenCalledTimes(1);
    });
    expect(api.updateAdminVoice.mock.calls[0]?.[0]).toBe(hidden.id);
    expect(api.updateAdminVoice.mock.calls[0]?.[1]).toEqual({
      name: "Kavya Two",
      tags: ["calm"],
      status: "ready",
    });
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("explains that exposing a voice generates a preview", async () => {
    const user = userEvent.setup();
    renderWithQuery(<EditVoiceDialog voice={hidden} />);

    await user.click(screen.getByRole("button", { name: "Edit Kavya" }));
    const dialog = await screen.findByRole("dialog");

    expect(
      within(dialog).getByText(/Exposing a voice generates its preview clip/),
    ).toBeInTheDocument();
    expect(within(dialog).getByRole("switch", { name: "Expose to users" })).not.toBeChecked();
  });

  it("asks for a change before saving and validates the fields", async () => {
    const user = userEvent.setup();
    renderWithQuery(<EditVoiceDialog voice={adminVoice()} />);

    await user.click(screen.getByRole("button", { name: "Edit Aria" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("switch", { name: "Expose to users" })).toBeChecked();
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Change at least one field");

    await user.clear(within(dialog).getByRole("textbox", { name: "Name" }));
    await user.clear(within(dialog).getByRole("textbox", { name: "Language" }));
    await user.type(within(dialog).getByRole("textbox", { name: "Language" }), "English!");
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));

    expect(await within(dialog).findByText("Enter a name.")).toBeInTheDocument();
    expect(within(dialog).getByText("Use a language code such as en or hi.")).toBeInTheDocument();
    expect(api.updateAdminVoice).not.toHaveBeenCalled();
  });

  it("keeps the dialog open and explains a preview failure", async () => {
    api.updateAdminVoice.mockRejectedValue(problem("voice_preview_failed", 502));
    const user = userEvent.setup();
    renderWithQuery(<EditVoiceDialog voice={hidden} />);

    await user.click(screen.getByRole("button", { name: "Edit Kavya" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("switch", { name: "Expose to users" }));
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "preview could not be generated",
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});

describe("tag input", () => {
  const controlled = (initial: string[] = []) => {
    const onChange = vi.fn();
    renderWithQuery(<TagInput label="Tags" value={initial} onChange={onChange} />);
    return onChange;
  };

  it("adds a tag with the button and with Enter, normalized to lowercase", async () => {
    const user = userEvent.setup();
    const onChange = controlled(["warm"]);

    await user.type(screen.getByRole("textbox", { name: "Tags" }), "Calm");
    await user.click(screen.getByRole("button", { name: "Add tag" }));
    await user.type(screen.getByRole("textbox", { name: "Tags" }), "deep{Enter}");

    expect(onChange).toHaveBeenNthCalledWith(1, ["warm", "calm"]);
    expect(onChange).toHaveBeenNthCalledWith(2, ["warm", "deep"]);
  });

  it("rejects duplicates and invalid tags with an accessible message", async () => {
    const user = userEvent.setup();
    const onChange = controlled(["warm"]);

    await user.type(screen.getByRole("textbox", { name: "Tags" }), "warm{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("already added");
    await user.clear(screen.getByRole("textbox", { name: "Tags" }));
    await user.type(screen.getByRole("textbox", { name: "Tags" }), "-bad{Enter}");

    expect(screen.getByRole("alert")).toHaveTextContent("lowercase letters");
    expect(screen.getByRole("textbox", { name: "Tags" })).toBeInvalid();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("removes a tag with a labelled button", async () => {
    const user = userEvent.setup();
    const onChange = controlled(["warm", "calm"]);

    await user.click(screen.getByRole("button", { name: "Remove tag warm" }));

    expect(onChange).toHaveBeenCalledWith(["calm"]);
  });
});

describe("regenerate preview", () => {
  it("regenerates the preview of a voice", async () => {
    api.regenerateVoicePreview.mockResolvedValue(adminVoice());
    const user = userEvent.setup();
    renderWithQuery(<RegeneratePreviewButton voice={adminVoice()} />);

    await user.click(screen.getByRole("button", { name: "Regenerate preview of Aria" }));

    await waitFor(() => {
      expect(api.regenerateVoicePreview).toHaveBeenCalledWith(adminVoice().id);
    });
  });

  it("explains a provider failure next to the button", async () => {
    api.regenerateVoicePreview.mockRejectedValue(problem("voice_provider_unavailable", 502));
    const user = userEvent.setup();
    renderWithQuery(<RegeneratePreviewButton voice={adminVoice()} />);

    await user.click(screen.getByRole("button", { name: "Regenerate preview of Aria" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("provider is unavailable");
    expect(screen.getByRole("button", { name: "Regenerate preview of Aria" })).toBeEnabled();
  });
});
