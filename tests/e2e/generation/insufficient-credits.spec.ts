import { expect, test } from "@playwright/test";

import { formatCredits } from "../../support/billing-ui.js";
import { configureBrowser } from "../../support/browser-auth.js";
import { signInAs } from "../../support/browser-session.js";
import { Creator, QUESTION } from "../../support/generation.js";
import { chooseLandscapeOnly, setLengthSeconds } from "../../support/generation-ui.js";

const DEFAULT_LENGTH_SECONDS = 60;
const AFFORDABLE_LENGTH_SECONDS = 10;

let creator: Creator;
let closeApi: () => Promise<void>;

test.beforeAll(async ({ playwright }) => {
  const api = await playwright.request.newContext();
  closeApi = async () => {
    await api.dispose();
  };
  creator = await Creator.funded(api, "pack_starter");
});

test.afterAll(async () => {
  await closeApi();
});

test.beforeEach(async ({ context }) => {
  await configureBrowser(context);
});

test("a creator whose balance does not cover the video sees the shortfall and a buy credits link instead of the submit button", async ({
  page,
}) => {
  const wallet = await creator.session.wallet();
  const estimate = await creator.estimate({
    durationSeconds: DEFAULT_LENGTH_SECONDS,
    aspects: ["16:9"],
  });
  expect(estimate.affordable).toBe(false);
  const shortfall = estimate.credits - wallet.available;
  expect(shortfall).toBeGreaterThan(0);

  await signInAs(page, creator.session);
  await page.goto("/create");
  await page.getByRole("textbox", { name: "What should the video explain?" }).fill(QUESTION);
  await expect(page.getByRole("slider", { name: "Video length in seconds" })).toHaveAttribute(
    "aria-valuenow",
    String(DEFAULT_LENGTH_SECONDS),
  );
  await chooseLandscapeOnly(page);

  await expect(
    page.getByText(`You need ${formatCredits(shortfall)} more credits for this video.`),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "Buy credits to continue" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Create video", exact: true })).toHaveCount(0);

  await setLengthSeconds(page, AFFORDABLE_LENGTH_SECONDS);
  await expect(page.getByText("Your balance covers this video.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Create video", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Buy credits to continue" })).toHaveCount(0);

  await setLengthSeconds(page, DEFAULT_LENGTH_SECONDS);
  await expect(
    page.getByText(`You need ${formatCredits(shortfall)} more credits for this video.`),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Create video", exact: true })).toHaveCount(0);
  await page.getByRole("link", { name: "Buy credits to continue" }).click();
  await expect(page).toHaveURL(/\/billing\/credits$/);

  expect((await creator.jobs()).items).toHaveLength(0);
  expect(await creator.session.wallet()).toEqual(wallet);
});
