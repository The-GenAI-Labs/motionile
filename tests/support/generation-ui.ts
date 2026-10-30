import {
  type Browser,
  expect,
  type Locator,
  type Page,
  type PlaywrightWorkerArgs,
} from "@playwright/test";

import { authOrigin, configureBrowser } from "./browser-auth.js";
import {
  COMPLETION_TIMEOUT_MS,
  Creator,
  type Job,
  type JobOptionsBody,
  prepareBuiltinVoice,
} from "./generation.js";

export const E2E_DURATION_SECONDS = 10;
export const FIXTURE_TIMEOUT_MS = COMPLETION_TIMEOUT_MS + 240000;
export const PAGE_STEP_TIMEOUT_MS = 180000;
export const PLAYBACK_TIMEOUT_MS = 60000;
export const BINARY_SEARCH_QUERY = "How does binary search work?";
export const DNS_QUERY = "How does DNS resolve a domain name?";
export const jobUrl = /\/jobs\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

const LENGTH_MIN_SECONDS = 10;
const LENGTH_STEP_SECONDS = 5;
const MINIMUM_PLAYED_SECONDS = 0.5;
const HAVE_CURRENT_DATA = 2;

export interface Workspace {
  creator: Creator;
  close: () => Promise<void>;
}

export interface AnonymousVisitor {
  page: Page;
  close: () => Promise<void>;
}

export async function openWorkspace(
  playwright: PlaywrightWorkerArgs["playwright"],
  productCode = "pack_creator",
): Promise<Workspace> {
  const api = await playwright.request.newContext();
  await prepareBuiltinVoice(api);
  const creator = await Creator.funded(api, productCode);
  return {
    creator,
    close: async () => {
      await api.dispose();
    },
  };
}

export async function startShortJob(
  creator: Creator,
  query: string,
  options: Partial<JobOptionsBody> = {},
): Promise<Job> {
  return creator.startJob(query, {
    durationSeconds: E2E_DURATION_SECONDS,
    aspects: ["16:9"],
    reviewStoryboard: false,
    ...options,
  });
}

export async function completeShortJob(creator: Creator, query: string): Promise<Job> {
  const started = await startShortJob(creator, query);
  return creator.waitForJob(started.id, ["completed"], COMPLETION_TIMEOUT_MS);
}

export async function waitForAvailableCredits(creator: Creator, expected: number): Promise<void> {
  await expect
    .poll(async () => (await creator.session.wallet()).available, {
      timeout: 60000,
      intervals: [250, 500, 1000],
    })
    .toBe(expected);
}

export async function catalogTopic(
  creator: Creator,
  title: string,
): Promise<{ id: string; slug: string; title: string }> {
  const response = await creator.session.json<{
    items: { id: string; slug: string; title: string }[];
  }>(await creator.call("GET", `/v1/catalog/search?q=${encodeURIComponent(title)}`), 200);
  const topic = response.items.find((item) => item.title === title);
  if (topic === undefined) throw new Error(`The seeded catalog has no topic titled ${title}`);
  return topic;
}

export function jobIdOf(page: Page): string {
  const id = new URL(page.url()).pathname.split("/").pop();
  if (id === undefined || id === "") throw new Error(`The page ${page.url()} is not a job page`);
  return id;
}

export async function setLengthSeconds(page: Page, seconds: number): Promise<void> {
  const steps = (seconds - LENGTH_MIN_SECONDS) / LENGTH_STEP_SECONDS;
  if (!Number.isInteger(steps) || steps < 0) {
    throw new Error(`${String(seconds)} seconds is not reachable with the length slider`);
  }
  const slider = page.getByRole("slider", { name: "Video length in seconds" });
  await slider.focus();
  await slider.press("Home");
  for (let step = 0; step < steps; step += 1) await slider.press("ArrowRight");
  await expect(slider).toHaveAttribute("aria-valuenow", String(seconds));
}

export async function chooseLandscapeOnly(page: Page): Promise<void> {
  const group = page.getByRole("group", { name: "Aspect ratios" });
  const landscape = group.getByRole("button", { name: "16:9 landscape", exact: true });
  if ((await landscape.getAttribute("aria-pressed")) !== "true") await landscape.click();
  for (const name of ["9:16 portrait", "1:1 square"]) {
    const other = group.getByRole("button", { name, exact: true });
    if ((await other.count()) > 0 && (await other.getAttribute("aria-pressed")) === "true") {
      await other.click();
    }
  }
  await expect(landscape).toHaveAttribute("aria-pressed", "true");
  await expect(group.locator("button[aria-pressed='true']")).toHaveCount(1);
}

export async function setStoryboardReview(page: Page, enabled: boolean): Promise<void> {
  const review = page.getByRole("switch", { name: "Review storyboard before rendering" });
  if (enabled) await review.check();
  else await review.uncheck();
}

export async function submitCreateForm(page: Page): Promise<string> {
  await page.getByRole("button", { name: "Create video", exact: true }).click();
  await expect(page).toHaveURL(jobUrl, { timeout: 60000 });
  return jobIdOf(page);
}

export async function createVideoFromQuery(
  page: Page,
  query: string,
  options: { seconds?: number; review?: boolean } = {},
): Promise<string> {
  await page.goto("/create");
  await expect(page.getByRole("heading", { name: "Create a video" })).toBeVisible();
  await page.getByRole("textbox", { name: "What should the video explain?" }).fill(query);
  await setLengthSeconds(page, options.seconds ?? E2E_DURATION_SECONDS);
  await chooseLandscapeOnly(page);
  await setStoryboardReview(page, options.review ?? false);
  return submitCreateForm(page);
}

export function statusBadge(page: Page, label: string): Locator {
  return page.getByLabel(`Status: ${label}`, { exact: true });
}

export function stageRow(page: Page, label: string): Locator {
  return page
    .getByRole("list", { name: "Video stages" })
    .getByRole("listitem")
    .filter({ hasText: label });
}

export async function expectVideoPlays(video: Locator): Promise<void> {
  await expect(video).toBeVisible({ timeout: PLAYBACK_TIMEOUT_MS });
  await expect
    .poll(() => video.evaluate((element: HTMLVideoElement) => element.readyState), {
      timeout: PLAYBACK_TIMEOUT_MS,
      intervals: [250, 500, 1000],
    })
    .toBeGreaterThanOrEqual(HAVE_CURRENT_DATA);
  expect(await video.evaluate((element: HTMLVideoElement) => element.error === null)).toBe(true);
  expect(await video.evaluate((element: HTMLVideoElement) => element.paused)).toBe(true);

  await video.click();

  await expect
    .poll(() => video.evaluate((element: HTMLVideoElement) => element.paused), {
      timeout: PLAYBACK_TIMEOUT_MS,
    })
    .toBe(false);
  await expect
    .poll(() => video.evaluate((element: HTMLVideoElement) => element.currentTime), {
      timeout: PLAYBACK_TIMEOUT_MS,
      intervals: [250, 500, 1000],
    })
    .toBeGreaterThan(MINIMUM_PLAYED_SECONDS);
  expect(await video.evaluate((element: HTMLVideoElement) => element.error === null)).toBe(true);
  await video.evaluate((element: HTMLVideoElement) => {
    element.pause();
  });
}

export async function expectVideoLoads(video: Locator): Promise<void> {
  await expect(video).toBeVisible({ timeout: PLAYBACK_TIMEOUT_MS });
  await expect
    .poll(() => video.evaluate((element: HTMLVideoElement) => element.readyState), {
      timeout: PLAYBACK_TIMEOUT_MS,
      intervals: [250, 500, 1000],
    })
    .toBeGreaterThanOrEqual(HAVE_CURRENT_DATA);
  expect(await video.evaluate((element: HTMLVideoElement) => element.error === null)).toBe(true);
  expect(await video.evaluate((element: HTMLVideoElement) => element.duration)).toBeGreaterThan(1);
}

export async function openAnonymousVisitor(browser: Browser): Promise<AnonymousVisitor> {
  const context = await browser.newContext({ baseURL: authOrigin, ignoreHTTPSErrors: true });
  await configureBrowser(context);
  return {
    page: await context.newPage(),
    close: async () => {
      await context.close();
    },
  };
}

export async function robotsDirective(page: Page): Promise<string> {
  const directives = await page
    .locator('meta[name="robots"]')
    .evaluateAll((tags) => tags.map((tag) => tag.getAttribute("content") ?? ""));
  return directives.join(", ");
}

export async function jsonLdTypes(page: Page): Promise<string[]> {
  const blocks = await page.locator('script[type="application/ld+json"]').allTextContents();
  return blocks.flatMap((block) => {
    const parsed = JSON.parse(block) as { "@type"?: string } | { "@type"?: string }[];
    return (Array.isArray(parsed) ? parsed : [parsed]).map((document) => document["@type"] ?? "");
  });
}

export function slugOf(url: string): string {
  const slug = new URL(url).pathname.split("/").pop();
  if (slug === undefined || slug === "") throw new Error(`${url} is not a share link`);
  return slug;
}
