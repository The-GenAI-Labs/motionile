import { randomBytes } from "node:crypto";

import { expect, test } from "@playwright/test";

import { signupWithRole } from "../../support/admin.js";
import { WAV_TYPE, wavBytes } from "../../support/audio.js";
import { configureBrowser } from "../../support/browser-auth.js";
import { signInAs } from "../../support/browser-session.js";
import { VoiceUser } from "../../support/voices.js";

const TONE_SECONDS = 8;
const LICENSE_URL = "https://example.com/licenses/e2e-tone";
const HIDDEN_VOICE = "Ravi";

test.beforeEach(async ({ context }) => {
  await configureBrowser(context);
});

test("an admin uploads a licensed track, sees it inactive, activates it and finds its preview control", async ({
  page,
  request,
}) => {
  test.setTimeout(180000);
  const admin = await signupWithRole(request, "super_admin");
  const suffix = randomBytes(4).toString("hex");
  const title = `E2E tone ${suffix}`;
  const mood = `e2e-${suffix}`;
  await signInAs(page, admin);

  await page.goto("/admin/music");
  await page.getByRole("button", { name: "Upload track", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Upload a music track" });
  await dialog.getByLabel("Audio file", { exact: true }).setInputFiles({
    name: `tone-${suffix}.wav`,
    mimeType: WAV_TYPE,
    buffer: wavBytes(TONE_SECONDS),
  });
  await dialog.getByLabel("Title", { exact: true }).fill(title);
  await dialog.getByLabel("Mood", { exact: true }).fill(mood);
  await dialog.getByLabel("License name", { exact: true }).fill("E2E test license");
  await dialog.getByLabel("License URL", { exact: true }).fill(LICENSE_URL);
  await dialog.getByRole("button", { name: "Upload track", exact: true }).click();
  await expect(dialog).toBeHidden({ timeout: 60000 });

  const filtered = page.waitForResponse(
    (response) =>
      response.url().includes("/v1/admin/music") && response.url().includes(`mood=${mood}`),
  );
  await page.getByRole("searchbox", { name: "Mood", exact: true }).fill(mood);
  expect((await filtered).ok()).toBe(true);
  const row = page.getByRole("row").filter({ hasText: title });
  await expect(row).toBeVisible();
  await expect(row.getByText("Inactive", { exact: true })).toBeVisible();
  await expect(row.getByRole("link", { name: "E2E test license", exact: true })).toHaveAttribute(
    "href",
    LICENSE_URL,
  );
  await expect(
    row.getByRole("button", { name: `Play preview of ${title}`, exact: true }),
  ).toBeVisible();

  await row.getByRole("button", { name: `Activate ${title}`, exact: true }).click();
  await page
    .getByRole("alertdialog")
    .getByRole("button", { name: "Activate", exact: true })
    .click();
  await expect(row.getByText("Active", { exact: true })).toBeVisible();
  await expect(row.getByRole("button", { name: `Deactivate ${title}`, exact: true })).toBeVisible();

  await row.getByRole("button", { name: `Play preview of ${title}`, exact: true }).click();
  await expect(page.getByLabel(`Preview of ${title}`, { exact: true })).toBeVisible();
});

test("an admin syncs the provider voices and exposes one of them", async ({ page, request }) => {
  test.setTimeout(120000);
  const admin = await signupWithRole(request, "super_admin");
  const voices = new VoiceUser(admin);
  const synced = await voices.syncBuiltinVoices();
  const target = synced.items.find((voice) => voice.name === HIDDEN_VOICE);
  if (target === undefined) throw new Error(`The provider has no voice named ${HIDDEN_VOICE}`);
  const hidden = await admin.call("PATCH", `/v1/admin/voices/${target.id}`, { status: "disabled" });
  expect(hidden.status(), await hidden.text()).toBe(200);
  await signInAs(page, admin);

  await page.goto("/admin/voices");
  await page.getByRole("button", { name: "Sync from provider", exact: true }).click();
  await expect(page.getByText(/Sync finished:/)).toBeVisible();

  const row = page.getByRole("row").filter({ hasText: HIDDEN_VOICE });
  await expect(row.getByText("Hidden", { exact: true })).toBeVisible();
  await row.getByRole("button", { name: `Edit ${HIDDEN_VOICE}`, exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Edit voice" });
  await dialog.getByRole("switch", { name: "Expose to users", exact: true }).check();
  await dialog.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(dialog).toBeHidden({ timeout: 60000 });

  await expect(row.getByText("Exposed", { exact: true })).toBeVisible();
  await expect(row.getByRole("button", { name: `Play preview of ${HIDDEN_VOICE}` })).toBeVisible();
});
