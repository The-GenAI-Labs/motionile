import { expect, test } from "@playwright/test";

import { authOrigin, configureBrowser } from "../../support/browser-auth.js";
import { signInAs } from "../../support/browser-session.js";
import type { Job } from "../../support/generation.js";
import {
  BINARY_SEARCH_QUERY,
  completeShortJob,
  expectVideoLoads,
  FIXTURE_TIMEOUT_MS,
  jsonLdTypes,
  openAnonymousVisitor,
  openWorkspace,
  robotsDirective,
  slugOf,
  type Workspace,
} from "../../support/generation-ui.js";

let workspace: Workspace;
let video: Job;
let title: string;

test.beforeAll(async ({ playwright }) => {
  test.setTimeout(FIXTURE_TIMEOUT_MS);
  workspace = await openWorkspace(playwright);
  video = await completeShortJob(workspace.creator, BINARY_SEARCH_QUERY);
  const item = (await workspace.creator.library()).items.find(
    (candidate) => candidate.jobId === video.id,
  );
  if (item === undefined) throw new Error("The completed video is missing from the library");
  title = item.title;
});

test.afterAll(async () => {
  await workspace.close();
});

test.beforeEach(async ({ context }) => {
  await configureBrowser(context);
  await context.grantPermissions(["clipboard-read", "clipboard-write"], { origin: authOrigin });
});

test("a creator shares a video privately, makes the page indexable with a new link and turns sharing off", async ({
  page,
  browser,
}) => {
  test.setTimeout(480000);
  const { creator } = workspace;
  const visitor = await openAnonymousVisitor(browser);
  try {
    await signInAs(page, creator.session);
    await page.goto("/library");
    await page.getByRole("button", { name: `Share ${title}`, exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Share this video" });
    await expect(dialog.getByLabel("Version to share")).toHaveValue("16:9");
    await expect(
      dialog.getByRole("switch", { name: "Let search engines index the page" }),
    ).not.toBeChecked();
    await dialog.getByRole("button", { name: "Create link", exact: true }).click();

    const publicLink = dialog.getByLabel("Public link");
    await expect(publicLink).toHaveValue(/\/v\/[^/]+$/);
    await expect(dialog.getByText("Search engines are asked not to index the page.")).toBeVisible();
    const privateUrl = await publicLink.inputValue();
    const privateSlug = slugOf(privateUrl);
    await dialog.getByRole("button", { name: "Copy link", exact: true }).click();
    await expect
      .poll(() => page.evaluate(() => navigator.clipboard.readText()), { timeout: 10000 })
      .toBe(privateUrl);
    await dialog.getByRole("button", { name: "Done", exact: true }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByRole("article").getByText("Shared", { exact: true })).toBeVisible();

    const privateResponse = await visitor.page.goto(`/v/${privateSlug}`);
    expect(privateResponse?.status()).toBe(200);
    await expect(visitor.page.getByRole("heading", { name: title, level: 1 })).toBeVisible();
    await expectVideoLoads(visitor.page.locator("video"));
    await expect(
      visitor.page.getByRole("heading", { name: "Made with Motionile", level: 2 }),
    ).toBeVisible();
    await expect(
      visitor.page.getByRole("link", { name: "Create your own video", exact: true }),
    ).toHaveAttribute("href", "/register");
    expect(await robotsDirective(visitor.page)).toContain("noindex");
    expect(await jsonLdTypes(visitor.page)).not.toContain("VideoObject");

    await page.getByRole("button", { name: `Share ${title}`, exact: true }).click();
    await expect(dialog.getByLabel("Public link")).toHaveValue(new RegExp(`/v/${privateSlug}$`));
    await expect(dialog.getByText(/This video is already shared\./)).toBeVisible();
    await dialog.getByRole("switch", { name: "Let search engines index the page" }).check();
    await dialog.getByRole("button", { name: "Create link", exact: true }).click();
    const indexableLink = dialog.getByLabel("Public link");
    await expect(dialog.getByText("Search engines may index the page.")).toBeVisible();
    const indexableUrl = await indexableLink.inputValue();
    const indexableSlug = slugOf(indexableUrl);
    expect(indexableSlug).not.toBe(privateSlug);
    await dialog.getByRole("button", { name: "Done", exact: true }).click();

    const indexableResponse = await visitor.page.goto(`/v/${indexableSlug}`);
    expect(indexableResponse?.status()).toBe(200);
    await expect(visitor.page.getByRole("heading", { name: title, level: 1 })).toBeVisible();
    await expectVideoLoads(visitor.page.locator("video"));
    const directive = await robotsDirective(visitor.page);
    expect(directive).toContain("index");
    expect(directive).not.toContain("noindex");
    expect(await jsonLdTypes(visitor.page)).toContain("VideoObject");

    const replacedResponse = await visitor.page.goto(`/v/${privateSlug}`);
    expect(replacedResponse?.status()).toBe(404);

    await page.getByRole("button", { name: `Share ${title}`, exact: true }).click();
    await dialog.getByRole("button", { name: "Turn off sharing", exact: true }).click();
    const confirmation = page.getByRole("alertdialog", { name: "Turn off sharing?" });
    await expect(confirmation).toBeVisible();
    await confirmation.getByRole("button", { name: "Turn off sharing", exact: true }).click();
    await expect(confirmation).toBeHidden();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(page.getByRole("article").getByText("Shared", { exact: true })).toHaveCount(0);

    const revokedResponse = await visitor.page.goto(`/v/${indexableSlug}`);
    expect(revokedResponse?.status()).toBe(404);
    await expect(visitor.page.getByRole("link", { name: "Create your own video" })).toHaveCount(0);
    expect(await robotsDirective(visitor.page)).toContain("noindex");
  } finally {
    await visitor.close();
  }
});
