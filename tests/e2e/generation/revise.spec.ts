import { expect, test } from "@playwright/test";

import { configureBrowser } from "../../support/browser-auth.js";
import { signInAs } from "../../support/browser-session.js";
import { COMPLETION_TIMEOUT_MS, type Job } from "../../support/generation.js";
import {
  BINARY_SEARCH_QUERY,
  completeShortJob,
  expectVideoLoads,
  FIXTURE_TIMEOUT_MS,
  jobIdOf,
  jobUrl,
  openWorkspace,
  statusBadge,
  type Workspace,
} from "../../support/generation-ui.js";

const INSTRUCTIONS = "Open with a short everyday example before the explanation.";

let workspace: Workspace;
let parent: Job;

test.beforeAll(async ({ playwright }) => {
  test.setTimeout(FIXTURE_TIMEOUT_MS);
  workspace = await openWorkspace(playwright);
  parent = await completeShortJob(workspace.creator, BINARY_SEARCH_QUERY);
});

test.afterAll(async () => {
  await workspace.close();
});

test.beforeEach(async ({ context }) => {
  await configureBrowser(context);
});

test("revising a finished video makes a new video and leaves the original untouched", async ({
  page,
}) => {
  test.setTimeout(COMPLETION_TIMEOUT_MS + 240000);
  const { creator } = workspace;
  await signInAs(page, creator.session);
  await page.goto(`/jobs/${parent.id}`);
  await expect(page.getByRole("heading", { name: "Your video" })).toBeVisible();

  await page.getByRole("button", { name: "Revise", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Revise this video" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Start revision", exact: true }).click();
  await expect(dialog.getByText("Tell Motionile what to change.")).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/jobs/${parent.id}$`));

  await dialog.getByRole("textbox", { name: "What should change?" }).fill(INSTRUCTIONS);
  await dialog.getByRole("button", { name: "Start revision", exact: true }).click();

  await expect.poll(() => jobIdOf(page), { timeout: 60000 }).not.toBe(parent.id);
  await expect(page).toHaveURL(jobUrl);
  const childId = jobIdOf(page);
  await expect(page.getByRole("list", { name: "Video stages" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Your video" })).toBeVisible({
    timeout: COMPLETION_TIMEOUT_MS,
  });
  await expect(statusBadge(page, "Completed")).toBeVisible();
  await expectVideoLoads(page.locator("video"));

  const child = await creator.fetchJob(childId);
  expect(child.status).toBe("completed");
  expect(child.parentJobId).toBe(parent.id);
  expect(child.renderId).not.toBeNull();
  expect(child.renderId).not.toBe(parent.renderId);

  const untouched = await creator.fetchJob(parent.id);
  expect(untouched.status).toBe("completed");
  expect(untouched.parentJobId).toBeNull();
  expect(untouched.renderId).toBe(parent.renderId);
  expect(untouched.creditsCharged).toBe(parent.creditsCharged);

  const library = await creator.library();
  const listed = library.items.map((item) => item.jobId);
  expect(listed).toContain(parent.id);
  expect(listed).toContain(childId);

  await page.goto(`/jobs/${parent.id}`);
  await expect(page.getByRole("heading", { name: "Your video" })).toBeVisible();
  await expectVideoLoads(page.locator("video"));
});
