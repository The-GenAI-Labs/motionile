import { expect, test } from "@playwright/test";

import { configureBrowser } from "../../support/browser-auth.js";
import { signInAs } from "../../support/browser-session.js";
import { COMPLETION_TIMEOUT_MS } from "../../support/generation.js";
import {
  catalogTopic,
  chooseLandscapeOnly,
  E2E_DURATION_SECONDS,
  expectVideoPlays,
  FIXTURE_TIMEOUT_MS,
  jobIdOf,
  jobUrl,
  openWorkspace,
  PAGE_STEP_TIMEOUT_MS,
  setLengthSeconds,
  stageRow,
  statusBadge,
  type Workspace,
} from "../../support/generation-ui.js";

const TOPIC_TITLE = "Linear Equations";

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

test("a creator turns a catalog topic into a short landscape video and plays it", async ({
  page,
}) => {
  test.setTimeout(COMPLETION_TIMEOUT_MS + 240000);
  const { creator } = workspace;
  const topic = await catalogTopic(creator, TOPIC_TITLE);
  await signInAs(page, creator.session);

  await page.goto(`/create?topic=${topic.slug}`);
  await expect(page.getByText(topic.title, { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Clear topic" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "What should the video explain?" })).toHaveCount(
    0,
  );
  await setLengthSeconds(page, E2E_DURATION_SECONDS);
  await chooseLandscapeOnly(page);
  await expect(page.getByText("Your balance covers this video.")).toBeVisible();
  await page.getByRole("button", { name: "Create video", exact: true }).click();

  await expect(page).toHaveURL(jobUrl, { timeout: 60000 });
  const jobId = jobIdOf(page);
  await expect(page.getByRole("heading", { name: topic.title, level: 1 })).toBeVisible();
  await expect(page.getByRole("list", { name: "Video stages" })).toBeVisible();
  await expect(stageRow(page, "Safety check")).toContainText("Done", {
    timeout: PAGE_STEP_TIMEOUT_MS,
  });
  await expect(page.getByRole("progressbar", { name: "Render progress" })).toBeVisible({
    timeout: COMPLETION_TIMEOUT_MS,
  });

  await expect(page.getByRole("heading", { name: "Your video" })).toBeVisible({
    timeout: COMPLETION_TIMEOUT_MS,
  });
  await expect(statusBadge(page, "Completed")).toBeVisible();
  await expectVideoPlays(page.locator("video"));

  const downloads = page.getByRole("list", { name: "Downloads" });
  const videoLink = downloads.getByRole("link", { name: "Download 16:9 landscape video" });
  const vttLink = downloads.getByRole("link", {
    name: "Download 16:9 landscape subtitles as VTT",
  });
  const srtLink = downloads.getByRole("link", {
    name: "Download 16:9 landscape subtitles as SRT",
  });
  await expect(downloads.getByRole("listitem")).toHaveCount(1);
  await expect(videoLink).toBeVisible();
  await expect(vttLink).toBeVisible();
  await expect(srtLink).toBeVisible();

  const video = await page.request.get((await videoLink.getAttribute("href")) ?? "", {
    headers: { Range: "bytes=0-1023" },
  });
  expect([200, 206]).toContain(video.status());
  const vtt = await page.request.get((await vttLink.getAttribute("href")) ?? "");
  expect(vtt.status()).toBe(200);
  expect(await vtt.text()).toMatch(/^WEBVTT/);
  const srt = await page.request.get((await srtLink.getAttribute("href")) ?? "");
  expect(srt.status()).toBe(200);
  expect(await srt.text()).toContain("-->");

  await page.getByText("How this video was made", { exact: true }).click();
  await expect(stageRow(page, "Rendering video")).toContainText("Done");
  await expect(stageRow(page, "Your review")).toContainText("Skipped");

  const job = await creator.fetchJob(jobId);
  expect(job.source).toBe("catalog");
  expect(job.status).toBe("completed");
  expect(job.renderId).not.toBeNull();
  expect(job.creditsCharged ?? 0).toBeGreaterThan(0);
  expect(job.creditsCharged ?? 0).toBeLessThanOrEqual(job.creditsReserved);
});
