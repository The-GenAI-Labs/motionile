import { expect, test } from "@playwright/test";

import { configureBrowser } from "../../support/browser-auth.js";
import { signInAs } from "../../support/browser-session.js";
import { COMPLETION_TIMEOUT_MS, type Job } from "../../support/generation.js";
import {
  BINARY_SEARCH_QUERY,
  DNS_QUERY,
  FIXTURE_TIMEOUT_MS,
  openWorkspace,
  startShortJob,
  type Workspace,
} from "../../support/generation-ui.js";

let workspace: Workspace;
let binarySearch: Job;
let dns: Job;
let binarySearchTitle: string;
let dnsTitle: string;

test.beforeAll(async ({ playwright }) => {
  test.setTimeout(FIXTURE_TIMEOUT_MS);
  workspace = await openWorkspace(playwright);
  const { creator } = workspace;
  const [first, second] = await Promise.all([
    startShortJob(creator, BINARY_SEARCH_QUERY),
    startShortJob(creator, DNS_QUERY),
  ]);
  [binarySearch, dns] = await Promise.all([
    creator.waitForJob(first.id, ["completed"], COMPLETION_TIMEOUT_MS),
    creator.waitForJob(second.id, ["completed"], COMPLETION_TIMEOUT_MS),
  ]);
  const items = (await creator.library()).items;
  const titleOf = (jobId: string): string => {
    const item = items.find((candidate) => candidate.jobId === jobId);
    if (item === undefined) throw new Error(`The video ${jobId} is missing from the library`);
    return item.title;
  };
  binarySearchTitle = titleOf(binarySearch.id);
  dnsTitle = titleOf(dns.id);
  if (binarySearchTitle === dnsTitle) throw new Error("The two videos share a title");
});

test.afterAll(async () => {
  await workspace.close();
});

test.beforeEach(async ({ context }) => {
  await configureBrowser(context);
});

test("finished videos appear in the library and in the dashboard's recent videos", async ({
  page,
}) => {
  await signInAs(page, workspace.creator.session);

  const recent = page.getByRole("region", { name: "Recent videos" });
  await expect(recent.getByRole("link", { name: binarySearchTitle })).toBeVisible();
  await expect(recent.getByRole("link", { name: dnsTitle })).toBeVisible();

  await page.goto("/library");
  await expect(page.getByRole("heading", { name: binarySearchTitle, level: 3 })).toBeVisible();
  await expect(page.getByRole("heading", { name: dnsTitle, level: 3 })).toBeVisible();
  await expect(page.getByRole("article")).toHaveCount(2);

  await page.getByRole("button", { name: `Play ${dnsTitle}`, exact: true }).click();
  const player = page.getByRole("dialog", { name: dnsTitle });
  await expect(player.locator("video")).toBeVisible();
  await expect(player.getByRole("button", { name: `Share ${dnsTitle}` })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(player).toBeHidden();
});

test("searching narrows the library to matching videos and clearing the filters restores it", async ({
  page,
}) => {
  await signInAs(page, workspace.creator.session);
  await page.goto("/library");
  await expect(page.getByRole("article")).toHaveCount(2);

  await page.getByRole("searchbox", { name: "Search videos" }).fill("binary search");
  await expect(page.getByRole("article")).toHaveCount(1);
  await expect(page.getByRole("heading", { name: binarySearchTitle, level: 3 })).toBeVisible();
  await expect(page.getByRole("heading", { name: dnsTitle, level: 3 })).toHaveCount(0);

  await page.getByRole("searchbox", { name: "Search videos" }).fill("no such video anywhere");
  await expect(page.getByRole("heading", { name: "No videos match" })).toBeVisible();
  await expect(page.getByRole("article")).toHaveCount(0);

  await page
    .getByRole("region", { name: "Library filters" })
    .getByRole("button", { name: "Clear filters" })
    .click();
  await expect(page.getByRole("searchbox", { name: "Search videos" })).toHaveValue("");
  await expect(page.getByRole("article")).toHaveCount(2);
});

test("the aspect ratio filter keeps only videos that have that version", async ({ page }) => {
  await signInAs(page, workspace.creator.session);
  await page.goto("/library");
  await expect(page.getByRole("article")).toHaveCount(2);

  const aspect = page.getByLabel("Aspect ratio", { exact: true });
  await aspect.selectOption({ label: "9:16 portrait" });
  await expect(page.getByRole("heading", { name: "No videos match" })).toBeVisible();
  await expect(page.getByRole("article")).toHaveCount(0);

  await aspect.selectOption({ label: "16:9 landscape" });
  await expect(page.getByRole("article")).toHaveCount(2);
  await expect(
    page.getByRole("article").first().getByRole("list", { name: "Details" }),
  ).toContainText("16:9");
});

test("deleting a video removes it from the library only after the creator confirms", async ({
  page,
}) => {
  const { creator } = workspace;
  await signInAs(page, creator.session);
  await page.goto("/library");
  await expect(page.getByRole("article")).toHaveCount(2);

  await page.getByRole("button", { name: `Delete ${dnsTitle}`, exact: true }).click();
  const confirmation = page.getByRole("alertdialog", { name: "Delete this video?" });
  await expect(confirmation).toBeVisible();
  await confirmation.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(confirmation).toBeHidden();
  await expect(page.getByRole("article")).toHaveCount(2);
  expect((await creator.library()).items).toHaveLength(2);

  await page.getByRole("button", { name: `Delete ${dnsTitle}`, exact: true }).click();
  await confirmation.getByRole("button", { name: "Delete video", exact: true }).click();
  await expect(confirmation).toBeHidden();

  await expect(page.getByRole("article")).toHaveCount(1);
  await expect(page.getByRole("heading", { name: dnsTitle, level: 3 })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: binarySearchTitle, level: 3 })).toBeVisible();
  const remaining = (await creator.library()).items.map((item) => item.jobId);
  expect(remaining).toEqual([binarySearch.id]);
  expect((await creator.call("GET", `/v1/jobs/${dns.id}`)).status()).toBe(404);

  await page.goto("/dashboard");
  const recent = page.getByRole("region", { name: "Recent videos" });
  await expect(recent.getByRole("link", { name: binarySearchTitle })).toBeVisible();
  await expect(recent.getByRole("link", { name: dnsTitle })).toHaveCount(0);
});
