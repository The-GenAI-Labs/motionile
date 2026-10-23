import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { type APIRequestContext, expect, type Locator, type Page, test } from "@playwright/test";

import { signupWithRole } from "../../support/admin.js";
import { configureBrowser } from "../../support/browser-auth.js";
import { signInAs } from "../../support/browser-session.js";
import { VoiceUser } from "../../support/voices.js";

const RENDER_TIMEOUT_MS = 480000;
const SEEK_SECONDS = 1;
const GOLDEN_TITLE = "Kinetic typography";
const TINY_FONT_RULE = ".words, .words * { font-size: 9px !important; }";
const renderUrl = /\/admin\/render\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

interface Narration {
  scenes: { sceneId: string; text: string }[];
}

const goldenDirectory = fileURLToPath(
  new URL("../../../apps/server/tests/fixtures/compositions/kinetic-typography/", import.meta.url),
);

function goldenComposition(): string {
  return readFileSync(`${goldenDirectory}composition.html`, "utf8");
}

function goldenNarration(): Narration {
  return JSON.parse(readFileSync(`${goldenDirectory}narration.json`, "utf8")) as Narration;
}

async function exposedAdmin(page: Page, request: APIRequestContext): Promise<void> {
  const admin = await signupWithRole(request, "super_admin");
  await new VoiceUser(admin).readyBuiltinVoice();
  await signInAs(page, admin);
}

async function chooseFirstVoice(scope: Locator): Promise<void> {
  const voice = scope.getByLabel("Voice", { exact: true });
  await expect(voice.locator("option")).not.toHaveCount(1);
  await voice.selectOption({ index: 1 });
}

async function keepOnly(scope: Locator, keep: readonly string[]): Promise<void> {
  for (const name of ["16:9 landscape", "9:16 portrait", "1:1 square"]) {
    const box = scope.getByRole("checkbox", { name, exact: true });
    if (keep.includes(name)) await box.check();
    else await box.uncheck();
  }
}

async function videoState(video: Locator): Promise<{
  readyState: number;
  duration: number;
  failed: boolean;
}> {
  return video.evaluate((element: HTMLVideoElement) => ({
    readyState: element.readyState,
    duration: element.duration,
    failed: element.error !== null,
  }));
}

test.beforeEach(async ({ context }) => {
  await configureBrowser(context);
});

test("an admin renders a golden composition with a fake voice, watches it finish and plays the result", async ({
  page,
  request,
}) => {
  test.setTimeout(RENDER_TIMEOUT_MS + 120000);
  await exposedAdmin(page, request);

  await page.goto("/admin/render");
  await page.getByRole("button", { name: `Render ${GOLDEN_TITLE}`, exact: true }).click();
  const dialog = page.getByRole("dialog", { name: `Render ${GOLDEN_TITLE}` });
  await chooseFirstVoice(dialog);
  await keepOnly(dialog, ["16:9 landscape", "9:16 portrait"]);
  await dialog.getByRole("button", { name: "Start render", exact: true }).click();

  await expect(page).toHaveURL(renderUrl);
  await expect(page.getByRole("progressbar", { name: "Render progress" })).toBeVisible();
  await expect(page.getByText("Completed", { exact: true })).toBeVisible({
    timeout: RENDER_TIMEOUT_MS,
  });
  await expect(page.getByRole("progressbar", { name: "Render progress" })).toHaveAttribute(
    "aria-valuenow",
    "100",
  );

  const report = page.getByRole("region", { name: "Validation report" });
  await expect(report).toContainText("The composition is valid");
  const timings = page.getByRole("region", { name: "Stage timings" });
  await expect(timings.getByRole("row", { name: /Capturing frames/ })).toBeVisible();
  await expect(timings.getByRole("row", { name: /Encoding/ })).toBeVisible();
  await expect(timings.getByRole("row", { name: /^Total/ })).toBeVisible();

  const player = page.getByRole("region", { name: "Test bed render" });
  const video = player.locator("video");
  await expect.poll(async () => (await videoState(video)).readyState).toBeGreaterThanOrEqual(1);
  const loaded = await videoState(video);
  expect(loaded.failed).toBe(false);
  expect(loaded.duration).toBeGreaterThan(SEEK_SECONDS);
  await expect(video.locator("track[kind='captions']")).toHaveCount(1);

  const switcher = player.getByRole("radiogroup", { name: "Aspect ratio" });
  const landscape = switcher.getByRole("radio", { name: "16:9 landscape", exact: true });
  const portrait = switcher.getByRole("radio", { name: "9:16 portrait", exact: true });
  await expect(landscape).toBeChecked();
  await video.evaluate(
    (element: HTMLVideoElement, seconds: number) =>
      new Promise<void>((resolve) => {
        element.addEventListener("seeked", () => {
          resolve();
        });
        element.currentTime = seconds;
      }),
    SEEK_SECONDS,
  );
  await landscape.focus();
  await page.keyboard.press("ArrowRight");
  await expect(portrait).toBeChecked();
  await expect(portrait).toBeFocused();
  await expect
    .poll(async () =>
      video.evaluate((element: HTMLVideoElement) =>
        element.readyState >= 1 ? element.currentTime : -1,
      ),
    )
    .toBeCloseTo(SEEK_SECONDS, 0);
  expect((await videoState(video)).failed).toBe(false);

  await page.keyboard.press("ArrowLeft");
  await expect(landscape).toBeChecked();
});

test("a composition with a tiny font fails validation and lists the issue with its scene, time and selector", async ({
  page,
  request,
}) => {
  test.setTimeout(RENDER_TIMEOUT_MS + 120000);
  await exposedAdmin(page, request);
  const composition = goldenComposition().replace("</style>", `${TINY_FONT_RULE}</style>`);
  expect(composition).toContain(TINY_FONT_RULE);

  await page.goto("/admin/render");
  await page.getByLabel("Composition HTML file", { exact: true }).setInputFiles({
    name: "tiny-font.html",
    mimeType: "text/html",
    buffer: Buffer.from(composition),
  });
  for (const scene of goldenNarration().scenes) {
    await page.getByLabel(`Narration for scene ${scene.sceneId}`, { exact: true }).fill(scene.text);
  }
  const upload = page.getByRole("form", { name: "Render a composition" });
  await chooseFirstVoice(upload);
  await keepOnly(upload, ["16:9 landscape"]);
  await upload.getByRole("button", { name: "Start render", exact: true }).click();

  await expect(page).toHaveURL(renderUrl);
  await expect(page.getByRole("heading", { name: "Render failed", level: 2 })).toBeVisible({
    timeout: RENDER_TIMEOUT_MS,
  });
  const failure = page.getByRole("region", { name: "Render failed" });
  await expect(failure).toContainText("validation_failed");
  await expect(failure).toContainText(
    "The composition has layout or timing errors. See the validation report below for each issue, with its scene, time and selector.",
  );

  const report = page.getByRole("region", { name: "Validation report" });
  const issue = report.getByRole("row").filter({ hasText: "font_too_small" }).first();
  await expect(issue).toBeVisible();
  const scene = goldenNarration().scenes.map((entry) => entry.sceneId);
  await expect(issue.getByRole("cell").nth(3)).toHaveText(new RegExp(`^(${scene.join("|")})$`));
  await expect(issue.getByRole("cell").nth(4)).toHaveText(/^\d+:\d{2}/);
  await expect(issue.getByRole("cell").nth(6)).not.toHaveText("-");
  await expect(page.getByText("Completed", { exact: true })).toHaveCount(0);
});
