import { fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NuqsTestingAdapter } from "nuqs/adapters/testing";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EditTrackDialog } from "@/features/admin-music/components/edit-track-dialog";
import { MusicTable } from "@/features/admin-music/components/music-table";
import { TrackActiveToggle } from "@/features/admin-music/components/track-active-toggle";
import { TrackPreview } from "@/features/admin-music/components/track-preview";
import { UploadTrackDialog } from "@/features/admin-music/components/upload-track-dialog";
import { ApiError } from "@/lib/api/api-error";
import { formatDate } from "@/lib/utils/format";

import { inactiveTrack, musicTrack, TRACK_ID } from "./admin-music-fixtures";
import { renderWithQuery } from "./render-with-query";

const api = vi.hoisted(() => ({
  listMusicTracks: vi.fn(),
  uploadMusicTrack: vi.fn(),
  updateMusicTrack: vi.fn(),
  activateMusicTrack: vi.fn(),
  deactivateMusicTrack: vi.fn(),
}));

vi.mock("@/features/admin-music/api/admin-music.api", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  ...api,
}));

const problem = (code: string, status: number) =>
  new ApiError({ kind: "http", status, code, title: code, detail: null });

const withNuqs = (ui: ReactElement, searchParams = "") => (
  <NuqsTestingAdapter searchParams={searchParams}>{ui}</NuqsTestingAdapter>
);

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(560);
  vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(1200);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("music table", () => {
  it("lists tracks with their metadata, license links and status", async () => {
    api.listMusicTracks.mockResolvedValue({
      items: [musicTrack(), inactiveTrack],
      nextCursor: null,
    });
    renderWithQuery(withNuqs(<MusicTable />));

    const table = await screen.findByRole("table", { name: "Music tracks" });

    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((header) => header.textContent),
    ).toEqual([
      "Title",
      "Mood",
      "BPM",
      "Duration",
      "License",
      "Status",
      "Uploaded",
      "Preview",
      "Actions",
    ]);
    const first = within(within(table).getByRole("row", { name: /Quiet Orbit/ }));
    expect(first.getByRole("cell", { name: /Quiet Orbit.*Composed by Ada/ })).toBeInTheDocument();
    expect(first.getByRole("cell", { name: "calm" })).toBeInTheDocument();
    expect(first.getByRole("cell", { name: "92" })).toBeInTheDocument();
    expect(first.getByRole("cell", { name: "2:05" })).toBeInTheDocument();
    expect(first.getByRole("link", { name: "CC BY 4.0" })).toHaveAttribute(
      "href",
      "https://creativecommons.org/licenses/by/4.0/",
    );
    expect(first.getByText("Active")).toBeInTheDocument();
    expect(first.getByText(formatDate(musicTrack().createdAt))).toBeInTheDocument();
    const second = within(within(table).getByRole("row", { name: /Neon Harbor/ }));
    expect(second.getByText("Inactive")).toBeInTheDocument();
    expect(second.getByText("No preview")).toBeInTheDocument();
    expect(second.getByRole("button", { name: "Activate Neon Harbor" })).toBeInTheDocument();
  });

  it("passes the filters from the address to the API", async () => {
    api.listMusicTracks.mockResolvedValue({ items: [], nextCursor: null });
    renderWithQuery(withNuqs(<MusicTable />, "?mood=calm&active=true"));

    expect(await screen.findByText("No music tracks match these filters.")).toBeVisible();

    expect(api.listMusicTracks).toHaveBeenCalledWith({ mood: "calm", active: true }, undefined);
    expect(screen.getByRole("searchbox", { name: "Mood" })).toHaveValue("calm");
    expect(screen.getByRole("combobox", { name: "Active" })).toHaveValue("true");
  });

  it("filters by active state through the select", async () => {
    const user = userEvent.setup();
    api.listMusicTracks.mockResolvedValue({ items: [musicTrack()], nextCursor: null });
    renderWithQuery(withNuqs(<MusicTable />));
    await screen.findByRole("table", { name: "Music tracks" });

    await user.selectOptions(screen.getByRole("combobox", { name: "Active" }), "No");

    await vi.waitFor(() => {
      expect(api.listMusicTracks).toHaveBeenLastCalledWith({ active: false }, undefined);
    });
  });

  it("loads the next page with the cursor", async () => {
    const user = userEvent.setup();
    api.listMusicTracks
      .mockResolvedValueOnce({ items: [musicTrack()], nextCursor: "cursor-2" })
      .mockResolvedValueOnce({ items: [inactiveTrack], nextCursor: null });
    renderWithQuery(withNuqs(<MusicTable />));

    await user.click(await screen.findByRole("button", { name: "Load more" }));

    expect(await screen.findByRole("cell", { name: "Neon Harbor" })).toBeInTheDocument();
    expect(api.listMusicTracks).toHaveBeenLastCalledWith({}, "cursor-2");
  });

  it("shows a loading state, then the mapped error with a retry", async () => {
    const user = userEvent.setup();
    api.listMusicTracks.mockRejectedValueOnce(problem("forbidden", 403));
    api.listMusicTracks.mockResolvedValue({ items: [musicTrack()], nextCursor: null });
    renderWithQuery(withNuqs(<MusicTable />));

    expect(screen.getByRole("status", { hidden: true })).toHaveAttribute(
      "aria-label",
      "Loading music tracks",
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Your account is not allowed to manage the music library.",
    );

    await user.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("table", { name: "Music tracks" })).toBeInTheDocument();
  });
});

describe("track preview", () => {
  it("plays the presigned preview inline on demand", async () => {
    const user = userEvent.setup();
    const { container } = renderWithQuery(<TrackPreview track={musicTrack()} />);
    expect(container.querySelector("audio")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Play preview of Quiet Orbit" }));

    const audio = screen.getByLabelText("Preview of Quiet Orbit", { selector: "audio" });
    expect(audio).toHaveAttribute("src", musicTrack().previewUrl);
    expect(audio).toHaveAttribute("controls");
    expect(audio).toHaveAttribute("preload", "none");
  });

  it("offers a refresh when the preview link has expired", async () => {
    const user = userEvent.setup();
    api.listMusicTracks.mockResolvedValue({ items: [], nextCursor: null });
    renderWithQuery(<TrackPreview track={musicTrack()} />);
    await user.click(screen.getByRole("button", { name: "Play preview of Quiet Orbit" }));

    fireEvent.error(screen.getByLabelText("Preview of Quiet Orbit", { selector: "audio" }));

    expect(screen.getByRole("alert")).toHaveTextContent("The preview link expired.");
    await user.click(screen.getByRole("button", { name: "Refresh preview" }));
    expect(screen.getByRole("button", { name: "Play preview of Quiet Orbit" })).toBeInTheDocument();
  });

  it("says so when the API exposes no preview", () => {
    renderWithQuery(<TrackPreview track={inactiveTrack} />);

    expect(screen.getByText("No preview")).toBeInTheDocument();
  });
});

describe("activate and deactivate", () => {
  it("asks for confirmation before deactivating", async () => {
    const user = userEvent.setup();
    api.deactivateMusicTrack.mockResolvedValue(musicTrack({ isActive: false }));
    api.listMusicTracks.mockResolvedValue({ items: [], nextCursor: null });
    renderWithQuery(<TrackActiveToggle track={musicTrack()} />);

    await user.click(screen.getByRole("button", { name: "Deactivate Quiet Orbit" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Deactivate this track?" });
    expect(api.deactivateMusicTrack).not.toHaveBeenCalled();
    expect(dialog).toHaveTextContent("Videos already rendered keep their mixed audio.");

    await user.click(within(dialog).getByRole("button", { name: "Deactivate" }));

    expect(api.deactivateMusicTrack).toHaveBeenCalledWith(TRACK_ID);
  });

  it("does nothing when the confirmation is cancelled", async () => {
    const user = userEvent.setup();
    renderWithQuery(<TrackActiveToggle track={musicTrack()} />);
    await user.click(screen.getByRole("button", { name: "Deactivate Quiet Orbit" }));

    await user.click(await screen.findByRole("button", { name: "Cancel" }));

    expect(api.deactivateMusicTrack).not.toHaveBeenCalled();
  });

  it("activates an inactive track and shows API errors in the dialog", async () => {
    const user = userEvent.setup();
    api.activateMusicTrack.mockRejectedValueOnce(problem("music_track_not_found", 404));
    renderWithQuery(<TrackActiveToggle track={inactiveTrack} />);

    await user.click(screen.getByRole("button", { name: "Activate Neon Harbor" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Activate this track?" });
    await user.click(within(dialog).getByRole("button", { name: "Activate" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "This track no longer exists. Reload the list.",
    );
    expect(api.activateMusicTrack).toHaveBeenCalledWith(inactiveTrack.id);
  });
});

const enterText = async (
  user: ReturnType<typeof userEvent.setup>,
  field: HTMLElement,
  text: string,
) => {
  await user.click(field);
  await user.paste(text);
};

const fillUpload = async (user: ReturnType<typeof userEvent.setup>, dialog: HTMLElement) => {
  await enterText(user, within(dialog).getByRole("textbox", { name: "Title" }), "Quiet Orbit");
  await enterText(user, within(dialog).getByRole("textbox", { name: "Mood" }), "calm");
  await enterText(user, within(dialog).getByRole("textbox", { name: "License name" }), "CC BY 4.0");
  await enterText(
    user,
    within(dialog).getByRole("textbox", { name: "License URL" }),
    "https://creativecommons.org/licenses/by/4.0/",
  );
};

describe("upload dialog", () => {
  const openDialog = async (user: ReturnType<typeof userEvent.setup>) => {
    renderWithQuery(<UploadTrackDialog />);
    await user.click(screen.getByRole("button", { name: "Upload track" }));
    return await screen.findByRole("dialog", { name: "Upload a music track" });
  };

  it("labels every field and validates before sending", async () => {
    const user = userEvent.setup();
    const dialog = await openDialog(user);

    for (const name of [
      "Audio file",
      "Title",
      "Mood",
      "BPM (optional)",
      "License name",
      "License URL",
      "Attribution text (optional)",
    ]) {
      expect(within(dialog).getByLabelText(name)).toBeInTheDocument();
    }
    expect(within(dialog).getByRole("checkbox", { name: "Activate on upload" })).not.toBeChecked();

    await user.click(within(dialog).getByRole("button", { name: "Upload track" }));

    expect(await within(dialog).findByText("Choose an audio file.")).toBeInTheDocument();
    expect(within(dialog).getByText("Title is required.")).toBeInTheDocument();
    expect(within(dialog).getByText(/lowercase letters, digits or hyphens/)).toBeInTheDocument();
    expect(within(dialog).getByText("Enter an https URL without spaces.")).toBeInTheDocument();
    expect(api.uploadMusicTrack).not.toHaveBeenCalled();
  });

  it("uploads the file with the metadata and closes on success", async () => {
    const user = userEvent.setup();
    api.uploadMusicTrack.mockResolvedValue(musicTrack());
    api.listMusicTracks.mockResolvedValue({ items: [], nextCursor: null });
    const dialog = await openDialog(user);
    const file = new File([new Uint8Array(32)], "orbit.mp3", { type: "audio/mpeg" });

    await user.upload(within(dialog).getByLabelText("Audio file"), file);
    await fillUpload(user, dialog);
    await user.type(within(dialog).getByRole("textbox", { name: "BPM (optional)" }), "92");
    await user.click(within(dialog).getByRole("checkbox", { name: "Activate on upload" }));
    await user.click(within(dialog).getByRole("button", { name: "Upload track" }));

    await vi.waitFor(() => {
      expect(api.uploadMusicTrack).toHaveBeenCalledTimes(1);
    });
    expect(api.uploadMusicTrack).toHaveBeenCalledWith({
      file,
      metadata: {
        title: "Quiet Orbit",
        mood: "calm",
        bpm: 92,
        licenseName: "CC BY 4.0",
        licenseUrl: "https://creativecommons.org/licenses/by/4.0/",
        activate: true,
      },
    });
    await vi.waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
  });

  it("maps the problem code of a rejected file to guidance and keeps the dialog open", async () => {
    const user = userEvent.setup();
    api.uploadMusicTrack.mockRejectedValue(problem("music_not_audio", 422));
    const dialog = await openDialog(user);

    await user.upload(
      within(dialog).getByLabelText("Audio file"),
      new File([new Uint8Array(8)], "notes.txt", { type: "audio/mpeg" }),
    );
    await fillUpload(user, dialog);
    await user.click(within(dialog).getByRole("button", { name: "Upload track" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "The file is not audio. Choose an MP3, M4A, WAV, FLAC or OGG file.",
    );
    expect(screen.getByRole("dialog", { name: "Upload a music track" })).toBeInTheDocument();
  });
});

describe("edit dialog", () => {
  const openEdit = async (user: ReturnType<typeof userEvent.setup>) => {
    renderWithQuery(<EditTrackDialog track={musicTrack()} />);
    await user.click(screen.getByRole("button", { name: "Edit Quiet Orbit" }));
    return await screen.findByRole("dialog", { name: "Edit track" });
  };

  it("prefills the metadata and has no file or activation field", async () => {
    const dialog = await openEdit(userEvent.setup());

    expect(within(dialog).getByRole("textbox", { name: "Title" })).toHaveValue("Quiet Orbit");
    expect(within(dialog).getByRole("textbox", { name: "Mood" })).toHaveValue("calm");
    expect(within(dialog).getByRole("textbox", { name: "BPM (optional)" })).toHaveValue("92");
    expect(within(dialog).queryByLabelText("Audio file")).toBeNull();
    expect(within(dialog).queryByRole("checkbox")).toBeNull();
  });

  it("saves only the changed fields", async () => {
    const user = userEvent.setup();
    api.updateMusicTrack.mockResolvedValue(musicTrack({ title: "Renamed" }));
    api.listMusicTracks.mockResolvedValue({ items: [], nextCursor: null });
    const dialog = await openEdit(user);

    const title = within(dialog).getByRole("textbox", { name: "Title" });
    await user.clear(title);
    await user.type(title, "Renamed");
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));

    await vi.waitFor(() => {
      expect(api.updateMusicTrack).toHaveBeenCalledWith(TRACK_ID, { title: "Renamed" });
    });
  });

  it("refuses to save without changes and shows validation errors", async () => {
    const user = userEvent.setup();
    const dialog = await openEdit(user);

    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "Change at least one field before saving.",
    );

    const url = within(dialog).getByRole("textbox", { name: "License URL" });
    await user.clear(url);
    await user.type(url, "http://insecure.example");
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));

    expect(await within(dialog).findByText("Enter an https URL without spaces.")).toBeVisible();
    expect(api.updateMusicTrack).not.toHaveBeenCalled();
  });

  it("shows the mapped error when the API rejects the update", async () => {
    const user = userEvent.setup();
    api.updateMusicTrack.mockRejectedValue(problem("music_track_not_found", 404));
    const dialog = await openEdit(user);
    const title = within(dialog).getByRole("textbox", { name: "Title" });
    await user.type(title, " II");

    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "This track no longer exists. Reload the list.",
    );
  });
});
