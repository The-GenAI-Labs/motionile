import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StoryboardEditor } from "@/features/generation/components/storyboard-editor";
import type { StoryboardView } from "@/features/generation/types/generation.types";
import { ApiError } from "@/lib/api/api-error";

import { job, JOB_ID, storyboardView } from "./generation-fixtures";
import { renderWithQuery } from "./render-with-query";

const api = vi.hoisted(() => ({
  updateStoryboard: vi.fn(),
  approveJob: vi.fn(),
  regenerateStoryboard: vi.fn(),
  getStoryboard: vi.fn(),
}));

vi.mock("@/features/generation/api/generation.api", () => api);

const editor = (view: StoryboardView = storyboardView(), onReload = vi.fn()) => {
  renderWithQuery(<StoryboardEditor jobId={JOB_ID} view={view} onReload={onReload} />);
  return { onReload };
};

const savedView = (version = 2) => storyboardView({ version });

const problem = (status: number, code: string, fieldErrors: ApiError["fieldErrors"] = []) =>
  new ApiError({ kind: "http", status, code, title: "Problem", detail: null, fieldErrors });

beforeEach(() => {
  vi.clearAllMocks();
  api.updateStoryboard.mockResolvedValue(savedView());
  api.approveJob.mockResolvedValue(job({ status: "voicing" }));
  api.regenerateStoryboard.mockResolvedValue(job({ status: "planning" }));
});

const narration = (number: number) =>
  screen.getByRole("textbox", { name: `Scene ${String(number)} narration` });

describe("StoryboardEditor", () => {
  it("shows every scene with labelled fields and a total against the request", () => {
    editor();
    expect(screen.getAllByRole("listitem", { name: /^Scene \d of 3$/ })).toHaveLength(3);
    expect(screen.getByRole("textbox", { name: "Scene 1 goal" })).toHaveValue("Goal 1");
    expect(screen.getByRole("textbox", { name: "Scene 2 visual brief" })).toHaveValue("Brief 2");
    expect(screen.getByRole("textbox", { name: /Scene 1 on-screen text/ })).toHaveValue("Key idea");
    expect(screen.getByRole("spinbutton", { name: "Scene 3 length in seconds" })).toHaveValue(4);
    expect(screen.getByText("Total 12.0 s of 12 s requested")).toBeInTheDocument();
    expect(screen.getByText(/The scenes match the requested length/)).toBeInTheDocument();
  });

  it("updates the spoken duration while typing and warns outside the allowed rate", async () => {
    const user = userEvent.setup();
    editor();
    expect(
      screen.getAllByText("10 words, about 4.2 seconds spoken at 2.4 words per second"),
    ).toHaveLength(3);
    await user.clear(narration(1));
    await user.type(narration(1), "one two three four five six");
    expect(
      screen.getByText("6 words, about 2.5 seconds spoken at 2.4 words per second"),
    ).toBeInTheDocument();
    expect(screen.getByText(/Warning: too few words for 4 seconds/)).toBeInTheDocument();

    const seconds = screen.getByRole("spinbutton", { name: "Scene 2 length in seconds" });
    await user.clear(seconds);
    await user.type(seconds, "2");
    expect(screen.getByText(/Warning: too many words for 2 seconds/)).toBeInTheDocument();
  });

  it("flags a total outside the tolerance", async () => {
    const user = userEvent.setup();
    editor();
    const seconds = screen.getByRole("spinbutton", { name: "Scene 1 length in seconds" });
    await user.clear(seconds);
    await user.type(seconds, "10");
    expect(screen.getByText("Total 18.0 s of 12 s requested")).toBeInTheDocument();
    expect(screen.getByText(/Warning: the scenes add up to more than/)).toBeInTheDocument();
  });

  it("rewrites positions when scenes are reordered with the buttons and saves them", async () => {
    const user = userEvent.setup();
    editor();
    await user.click(screen.getByRole("button", { name: "Move scene 1 down" }));
    expect(screen.getByRole("textbox", { name: "Scene 1 goal" })).toHaveValue("Goal 2");
    expect(screen.getByRole("textbox", { name: "Scene 2 goal" })).toHaveValue("Goal 1");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => {
      expect(api.updateStoryboard).toHaveBeenCalledTimes(1);
    });
    const [jobId, input] = api.updateStoryboard.mock.calls[0] as [
      string,
      { expectedVersion: number; content: StoryboardView["content"] },
    ];
    expect(jobId).toBe(JOB_ID);
    expect(input.expectedVersion).toBe(1);
    expect(input.content.scenes.map((scene) => [scene.id, scene.position])).toEqual([
      ["s2", 0],
      ["s1", 1],
      ["s3", 2],
    ]);
  });

  it("disables moves at the ends of the list", () => {
    editor();
    expect(screen.getByRole("button", { name: "Move scene 1 up" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Move scene 3 down" })).toBeDisabled();
  });

  it("adds scenes up to the limit and removes down to the minimum", async () => {
    const user = userEvent.setup();
    editor();
    await user.click(screen.getByRole("button", { name: "Add scene" }));
    expect(screen.getAllByRole("listitem", { name: /^Scene \d of 4$/ })).toHaveLength(4);
    expect(screen.getByRole("button", { name: "Add scene" })).toBeDisabled();
    expect(screen.getByText(/4 of 4 scenes/)).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Scene 4 goal" })).toHaveValue("");

    await user.click(screen.getByRole("button", { name: "Remove scene 4" }));
    await user.click(screen.getByRole("button", { name: "Remove scene 3" }));
    expect(screen.getAllByRole("listitem", { name: /^Scene \d of 2$/ })).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Remove scene 1" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Remove scene 2" })).toBeDisabled();
  });

  it("names a new scene with an unused id", async () => {
    const user = userEvent.setup();
    editor();
    await user.click(screen.getByRole("button", { name: "Remove scene 2" }));
    await user.click(screen.getByRole("button", { name: "Add scene" }));
    await user.type(screen.getByRole("textbox", { name: "Scene 3 goal" }), "New goal");
    await user.type(narration(3), "A new line of narration");
    await user.type(screen.getByRole("textbox", { name: "Scene 3 visual brief" }), "New brief");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => {
      expect(api.updateStoryboard).toHaveBeenCalled();
    });
    const input = api.updateStoryboard.mock.calls[0]?.[1] as {
      content: StoryboardView["content"];
    };
    expect(input.content.scenes.map((scene) => scene.id)).toEqual(["s1", "s3", "s4"]);
  });

  it("shows validation errors on empty fields and does not save", async () => {
    const user = userEvent.setup();
    editor();
    await user.clear(narration(2));
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("Write the narration for this scene.")).toBeInTheDocument();
    expect(api.updateStoryboard).not.toHaveBeenCalled();
  });

  it("shows server issues next to their scene and blocks approval until they are fixed", () => {
    editor(
      storyboardView({
        issues: [
          {
            code: "speaking_rate_high",
            sceneId: "s2",
            message: "Scene 2 is spoken too fast.",
          },
          { code: "total_duration", message: "The scenes are too long overall." },
        ],
      }),
    );
    const list = screen.getByRole("list", { name: "Problems with scene 2" });
    expect(list).toHaveTextContent("Scene 2 is spoken too fast.");
    expect(screen.getByRole("list", { name: "Storyboard problems" })).toHaveTextContent(
      "The scenes are too long overall.",
    );
    expect(screen.getByRole("button", { name: "Approve and continue" })).toBeDisabled();
    expect(
      screen.getByText(/Fix the highlighted problems and save before approving/),
    ).toBeInTheDocument();
  });

  it("maps a rejected save to the scene it names", async () => {
    const user = userEvent.setup();
    api.updateStoryboard.mockRejectedValue(
      problem(422, "storyboard_invalid", [
        {
          field: "content.scenes.1",
          message: "Scene 2 is spoken too fast.",
          type: "speaking_rate_high",
        },
      ]),
    );
    editor();
    await user.type(narration(1), " extra");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    const list = await screen.findByRole("list", { name: "Problems with scene 2" });
    expect(list).toHaveTextContent("Scene 2 is spoken too fast.");
    expect(screen.getByText(/The storyboard has problems/)).toBeInTheDocument();
  });

  it("offers a reload when the storyboard changed under the user", async () => {
    const user = userEvent.setup();
    api.updateStoryboard.mockRejectedValue(problem(409, "storyboard_version_conflict"));
    const fresh = storyboardView({ version: 3 });
    const { onReload } = editor(storyboardView(), vi.fn().mockResolvedValue(fresh));
    await user.type(narration(1), " extra");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText(/changed since you opened it/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Reload the latest storyboard" }));
    await waitFor(() => {
      expect(onReload).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      expect(narration(1)).toHaveValue(fresh.content.scenes[0]?.narration);
    });
    expect(screen.queryByText(/changed since you opened it/)).not.toBeInTheDocument();
  });

  it("approves a saved storyboard at its version", async () => {
    const user = userEvent.setup();
    editor();
    await user.click(screen.getByRole("button", { name: "Approve and continue" }));
    await waitFor(() => {
      expect(api.approveJob).toHaveBeenCalledWith(JOB_ID, 1);
    });
    expect(api.updateStoryboard).not.toHaveBeenCalled();
  });

  it("saves an unsaved draft first and approves the version it created", async () => {
    const user = userEvent.setup();
    editor();
    await user.type(narration(1), " extra");
    await user.click(screen.getByRole("button", { name: "Save and approve" }));
    await waitFor(() => {
      expect(api.approveJob).toHaveBeenCalledWith(JOB_ID, 2);
    });
    expect(api.updateStoryboard).toHaveBeenCalledTimes(1);
  });

  it("does not approve when saving the draft fails", async () => {
    const user = userEvent.setup();
    api.updateStoryboard.mockRejectedValue(problem(422, "storyboard_invalid"));
    editor();
    await user.type(narration(1), " extra");
    await user.click(screen.getByRole("button", { name: "Save and approve" }));
    expect(await screen.findByText(/The storyboard has problems/)).toBeInTheDocument();
    expect(api.approveJob).not.toHaveBeenCalled();
  });

  it("keeps save disabled until something changes", async () => {
    const user = userEvent.setup();
    editor();
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
    await user.type(narration(1), "!");
    expect(screen.getByRole("button", { name: "Save changes" })).toBeEnabled();
  });

  it("sends regeneration instructions", async () => {
    const user = userEvent.setup();
    editor();
    await user.click(screen.getByRole("button", { name: "Regenerate with instructions" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(screen.getByRole("button", { name: "Regenerate" }));
    expect(await screen.findByText("Tell Motionile what to change.")).toBeInTheDocument();
    await user.type(screen.getByRole("textbox", { name: "Instructions" }), "Make it shorter");
    await user.click(screen.getByRole("button", { name: "Regenerate" }));
    await waitFor(() => {
      expect(api.regenerateStoryboard).toHaveBeenCalledWith(JOB_ID, "Make it shorter");
    });
    await waitFor(() => {
      expect(dialog).not.toBeInTheDocument();
    });
  });
});
