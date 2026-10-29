import { expect, test } from "@playwright/test";

import { configureBrowser } from "../../support/browser-auth.js";
import { signInAs } from "../../support/browser-session.js";
import { COMPLETION_TIMEOUT_MS } from "../../support/generation.js";
import {
  BINARY_SEARCH_QUERY,
  createVideoFromQuery,
  expectVideoLoads,
  FIXTURE_TIMEOUT_MS,
  openWorkspace,
  PAGE_STEP_TIMEOUT_MS,
  statusBadge,
  type Workspace,
} from "../../support/generation-ui.js";

const OVERLONG_NARRATION =
  "This narration keeps going far beyond what the scene can speak. ".repeat(20);

let workspace: Workspace;

test.beforeAll(async ({ playwright }) => {
  test.setTimeout(FIXTURE_TIMEOUT_MS);
  workspace = await openWorkspace(playwright);
});

test.afterAll(async () => {
  await workspace.close();
});

test.beforeEach(async ({ context }) => {
  await configureBrowser(context);
});

test("a creator edits, reorders and fixes the storyboard, then approves it and gets the video", async ({
  page,
}) => {
  test.setTimeout(COMPLETION_TIMEOUT_MS + 360000);
  const { creator } = workspace;
  await signInAs(page, creator.session);

  const jobId = await createVideoFromQuery(page, BINARY_SEARCH_QUERY, { review: true });
  await expect(statusBadge(page, "Waiting for your approval")).toBeVisible({
    timeout: PAGE_STEP_TIMEOUT_MS,
  });
  await expect(page.getByRole("heading", { name: "Review the storyboard" })).toBeVisible();

  const original = await creator.storyboardView(jobId);
  const originalScenes = original.content.scenes;
  expect(originalScenes).toHaveLength(2);
  const [first, second] = originalScenes;
  if (first === undefined || second === undefined) throw new Error("The storyboard has no scenes");

  const editor = page.getByRole("form", { name: "Storyboard editor" });
  const sceneItems = editor.getByRole("list", { name: "Scenes" }).locator(":scope > li");
  await expect(sceneItems).toHaveCount(originalScenes.length);
  await expect(editor.getByText("The scenes match the requested length.")).toBeVisible();
  await expect(editor.getByRole("button", { name: "Save changes" })).toBeDisabled();
  await expect(editor.getByRole("button", { name: "Approve and continue" })).toBeEnabled();

  const editedNarration = `Edited ${first.narration.split(/\s+/).slice(1).join(" ")}`;
  const narrationOne = editor.getByRole("textbox", { name: "Scene 1 narration" });
  const narrationTwo = editor.getByRole("textbox", { name: "Scene 2 narration" });
  await expect(narrationOne).toHaveValue(first.narration);
  await narrationOne.fill(editedNarration);
  await expect(editor.getByRole("button", { name: "Save changes" })).toBeEnabled();
  await expect(editor.getByRole("button", { name: "Save and approve" })).toBeEnabled();

  await editor.getByRole("button", { name: "Move scene 1 down" }).click();
  await expect(narrationOne).toHaveValue(second.narration);
  await expect(narrationTwo).toHaveValue(editedNarration);
  await expect(editor.getByRole("button", { name: "Move scene 1 up" })).toBeDisabled();
  await expect(editor.getByRole("button", { name: "Move scene 2 down" })).toBeDisabled();

  const addedNumber = originalScenes.length + 1;
  await editor.getByRole("button", { name: "Add scene" }).click();
  await expect(sceneItems).toHaveCount(addedNumber);
  await expect(
    editor.getByRole("textbox", { name: `Scene ${String(addedNumber)} narration` }),
  ).toHaveValue("");
  await editor.getByRole("button", { name: `Remove scene ${String(addedNumber)}` }).click();
  await expect(sceneItems).toHaveCount(originalScenes.length);
  await expect(editor.getByRole("button", { name: "Remove scene 1" })).toBeDisabled();
  await expect(narrationOne).toHaveValue(second.narration);
  await expect(narrationTwo).toHaveValue(editedNarration);

  await narrationOne.fill(OVERLONG_NARRATION);
  await expect(editor.getByText(/Warning: too many words for/)).toBeVisible();
  await editor.getByRole("button", { name: "Save and approve" }).click();
  await expect(
    editor.getByRole("alert").filter({ hasText: "The storyboard has problems." }),
  ).toBeVisible();
  await expect(editor.getByRole("list", { name: "Problems with scene 1" })).toBeVisible();
  await expect(editor.getByRole("button", { name: "Save changes" })).toBeEnabled();
  expect((await creator.fetchJob(jobId)).status).toBe("awaiting_approval");
  expect((await creator.storyboardView(jobId)).version).toBe(original.version);
  await expect(statusBadge(page, "Waiting for your approval")).toBeVisible();

  await narrationOne.fill(second.narration);
  await expect(editor.getByText(/Warning: too many words for/)).toHaveCount(0);
  await editor.getByRole("button", { name: "Save changes" }).click();
  await expect(editor.getByRole("button", { name: "Save changes" })).toBeDisabled();
  await expect(editor.getByRole("list", { name: "Problems with scene 1" })).toHaveCount(0);
  await expect(editor.getByRole("alert")).toHaveCount(0);
  const saved = await creator.storyboardView(jobId);
  expect(saved.version).toBe(original.version + 1);
  expect(saved.approved).toBe(false);
  expect(saved.content.scenes.map((scene) => scene.id)).toEqual([second.id, first.id]);
  expect(saved.content.scenes.map((scene) => scene.narration)).toEqual([
    second.narration,
    editedNarration,
  ]);

  await editor.getByRole("button", { name: "Approve and continue" }).click();
  await expect(page.getByRole("heading", { name: "Review the storyboard" })).toHaveCount(0, {
    timeout: PAGE_STEP_TIMEOUT_MS,
  });

  await expect(page.getByRole("heading", { name: "Your video" })).toBeVisible({
    timeout: COMPLETION_TIMEOUT_MS,
  });
  await expect(statusBadge(page, "Completed")).toBeVisible();
  await expectVideoLoads(page.locator("video"));

  const approved = await creator.storyboardView(jobId);
  expect(approved.approved).toBe(true);
  expect(approved.version).toBe(saved.version);
  expect(approved.content.scenes.map((scene) => scene.narration)).toEqual([
    second.narration,
    editedNarration,
  ]);
  const job = await creator.fetchJob(jobId);
  expect(job.status).toBe("completed");
  expect(job.renderId).not.toBeNull();
});
