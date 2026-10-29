import { expect, type Page, test } from "@playwright/test";

import { configureBrowser } from "../../support/browser-auth.js";
import { signInAs } from "../../support/browser-session.js";
import {
  BINARY_SEARCH_QUERY,
  E2E_DURATION_SECONDS,
  FIXTURE_TIMEOUT_MS,
  openWorkspace,
  PAGE_STEP_TIMEOUT_MS,
  startShortJob,
  statusBadge,
  waitForAvailableCredits,
  type Workspace,
} from "../../support/generation-ui.js";

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

async function cancelFromPage(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Cancel video", exact: true }).click();
  const confirmation = page.getByRole("alertdialog", { name: "Cancel this video?" });
  await expect(confirmation).toBeVisible();
  await confirmation.getByRole("button", { name: "Cancel video", exact: true }).click();
  await expect(confirmation).toBeHidden();
}

async function expectCancelledPage(page: Page): Promise<void> {
  await expect(statusBadge(page, "Cancelled")).toBeVisible({ timeout: PAGE_STEP_TIMEOUT_MS });
  await expect(page.getByRole("heading", { name: "Video cancelled" })).toBeVisible();
  await expect(
    page.getByText(/credits were held for this video and have been returned to your balance\./),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "Try again" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Cancel video", exact: true })).toHaveCount(0);
}

test("cancelling a storyboard that waits for approval returns every held credit", async ({
  page,
}) => {
  test.setTimeout(PAGE_STEP_TIMEOUT_MS * 3);
  const { creator } = workspace;
  const before = await creator.session.wallet();

  const waiting = await creator.awaitingApproval(BINARY_SEARCH_QUERY, {
    durationSeconds: E2E_DURATION_SECONDS,
    aspects: ["16:9"],
  });
  expect(waiting.creditsReserved).toBeGreaterThan(0);
  const held = await creator.session.wallet();
  expect(held.reserved).toBe(waiting.creditsReserved);
  expect(held.available).toBe(before.available - waiting.creditsReserved);

  await signInAs(page, creator.session);
  await page.goto(`/jobs/${waiting.id}`);
  await expect(statusBadge(page, "Waiting for your approval")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Review the storyboard" })).toBeVisible();
  await cancelFromPage(page);

  await expectCancelledPage(page);
  await expect(page.getByRole("heading", { name: "Review the storyboard" })).toHaveCount(0);
  const cancelled = await creator.fetchJob(waiting.id);
  expect(cancelled.status).toBe("cancelled");
  expect(cancelled.renderId).toBeNull();
  expect(cancelled.creditsCharged ?? 0).toBe(0);
  await waitForAvailableCredits(creator, before.available);
  expect(await creator.session.wallet()).toEqual(before);
});

test("cancelling a video while it is being made stops the work and returns every held credit", async ({
  page,
}) => {
  test.setTimeout(PAGE_STEP_TIMEOUT_MS * 3);
  const { creator } = workspace;
  const before = await creator.session.wallet();

  const running = await startShortJob(creator, BINARY_SEARCH_QUERY);
  expect(running.creditsReserved).toBeGreaterThan(0);

  await signInAs(page, creator.session);
  await page.goto(`/jobs/${running.id}`);
  await expect(page.getByRole("list", { name: "Video stages" })).toBeVisible();
  await expect(statusBadge(page, "Completed")).toHaveCount(0);
  await cancelFromPage(page);

  await expectCancelledPage(page);
  const cancelled = await creator.fetchJob(running.id);
  expect(cancelled.status).toBe("cancelled");
  expect(cancelled.creditsCharged ?? 0).toBe(0);
  await waitForAvailableCredits(creator, before.available);
  expect(await creator.session.wallet()).toEqual(before);
});
