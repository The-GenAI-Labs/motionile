import { expect, type Page, test } from "@playwright/test";

import { signupWithRole } from "../../support/admin.js";
import { buyPack, FakeRazorpay } from "../../support/billing.js";
import { configureBrowser } from "../../support/browser-auth.js";
import { signInAs } from "../../support/browser-session.js";
import { VoiceUser } from "../../support/voices.js";

const GENERATION_TIMEOUT_MS = 480000;
const QUESTION = "How does a hash map handle collisions?";
const jobUrl = /\/jobs\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

test.beforeEach(async ({ context }) => {
  await configureBrowser(context);
});

async function fundedCreator(page: Page, request: Parameters<typeof signupWithRole>[0]) {
  const creator = await signupWithRole(request, "super_admin");
  await new VoiceUser(creator).readyBuiltinVoice();
  await buyPack(creator, new FakeRazorpay(request), "pack_creator");
  await creator.waitForBalance(500);
  await signInAs(page, creator);
}

test("a creator asks a question, reviews the storyboard, approves it and watches the finished video", async ({
  page,
  request,
}) => {
  test.setTimeout(GENERATION_TIMEOUT_MS + 120000);
  await fundedCreator(page, request);

  await page.goto("/create");
  await expect(page.getByRole("heading", { name: "Create a video" })).toBeVisible();
  await page.getByRole("textbox", { name: "What should the video explain?" }).fill(QUESTION);
  await expect(page.getByRole("slider", { name: "Video length in seconds" })).toHaveAttribute(
    "aria-valuenow",
    "60",
  );
  await expect(page.getByText("Your balance covers this video.")).toBeVisible();
  await page.getByRole("switch", { name: "Review storyboard before rendering" }).click();
  await page.getByRole("button", { name: "Create video" }).click();

  await expect(page).toHaveURL(jobUrl);
  await expect(page.getByRole("list", { name: "Video stages" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Review the storyboard" })).toBeVisible({
    timeout: GENERATION_TIMEOUT_MS,
  });

  const editor = page.getByRole("form", { name: "Storyboard editor" });
  const narration = editor.getByRole("textbox", { name: "Scene 1 narration" });
  await expect(narration).not.toHaveValue("");
  await editor.getByRole("button", { name: "Move scene 1 down" }).click();
  await expect(editor.getByRole("button", { name: "Save changes" })).toBeEnabled();
  await editor.getByRole("button", { name: "Save and approve" }).click();

  await expect(page.locator("video").first()).toBeVisible({
    timeout: GENERATION_TIMEOUT_MS,
  });
  await expect(page.getByRole("heading", { name: "Your video" })).toBeVisible();
  await expect(page.getByRole("link", { name: /^Download 16:9 landscape video$/ })).toBeVisible();
  await expect(page.getByRole("button", { name: "Revise" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Publish" })).toHaveCount(0);
});

test("a creator without enough credits is sent to buy credits", async ({ page, request }) => {
  const creator = await signupWithRole(request, "super_admin");
  await signInAs(page, creator);

  await page.goto("/create");
  await page.getByRole("textbox", { name: "What should the video explain?" }).fill(QUESTION);
  const buy = page.getByRole("link", { name: "Buy credits to continue" });
  await expect(buy).toBeVisible();
  await expect(page.getByRole("button", { name: "Create video" })).toHaveCount(0);
  await buy.click();
  await expect(page).toHaveURL(/\/billing\/credits$/);
});
