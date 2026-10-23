import { randomUUID } from "node:crypto";

import { expect, type Page, test } from "@playwright/test";

import { WAV_TYPE, wavBytes } from "../../support/audio.js";
import { authOrigin, configureBrowser, registerApi } from "../../support/browser-auth.js";
import { browserApi } from "../../support/browser-session.js";
import { clearConsentTranscript, setConsentTranscript } from "../../support/consent-transcript.js";

const SAMPLE_SECONDS = 16;
const SAMPLE_COUNT = 2;
const CLONE_TIMEOUT_MS = 180000;
const MISMATCH_GUIDANCE =
  "What you said did not match the consent sentence. Start again and read the sentence exactly as shown, in a quiet room.";

interface VoiceSummary {
  id: string;
  name: string;
  kind: string;
  status: string;
  failureCode: string | null;
}

test.describe.configure({ mode: "serial" });

test.use({
  launchOptions: {
    args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"],
  },
});

test.beforeEach(async ({ context }) => {
  await configureBrowser(context);
  await context.grantPermissions(["microphone"], { origin: authOrigin });
});

function voiceName(): string {
  return `E2E voice ${randomUUID().slice(0, 8)}`;
}

async function acceptConsent(page: Page): Promise<void> {
  await page.goto("/settings/voices/new");
  await page.getByRole("checkbox", { name: /I have read and accept this statement/ }).check();
  await page.getByRole("button", { name: "Accept and continue", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Step 2 of 5: Consent recording", level: 2 }),
  ).toBeVisible();
}

async function recordAndUploadConsent(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Start recording", exact: true }).click();
  await expect(page.getByRole("timer", { name: "Recording length" })).toContainText(/^00:0[5-9]/);
  await page.getByRole("button", { name: "Stop recording", exact: true }).click();
  await page.getByRole("button", { name: "Upload this recording", exact: true }).click();
  await expect(page.getByText(/Consent recording uploaded/)).toBeVisible();
  await page.getByRole("button", { name: "Continue to voice samples", exact: true }).click();
}

async function uploadSamples(page: Page): Promise<void> {
  await expect(
    page.getByRole("heading", { name: "Step 3 of 5: Voice samples", level: 2 }),
  ).toBeVisible();
  await page.getByLabel("Upload voice sample files", { exact: true }).setInputFiles(
    Array.from({ length: SAMPLE_COUNT }, (_, index) => ({
      name: `sample-${String(index + 1)}.wav`,
      mimeType: WAV_TYPE,
      buffer: wavBytes(SAMPLE_SECONDS),
    })),
  );
  await expect(page.getByRole("list", { name: "Added samples" }).getByRole("listitem")).toHaveCount(
    SAMPLE_COUNT,
  );
  await page.getByRole("button", { name: "Continue to name and language", exact: true }).click();
}

async function submitClone(page: Page, name: string): Promise<void> {
  await page.getByLabel("Voice name", { exact: true }).fill(name);
  await page.getByRole("button", { name: "Create my voice", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Step 5 of 5: Status", level: 2 })).toBeVisible();
}

async function cloneWithTranscript(
  page: Page,
  name: string,
  transcript: (sentence: string) => string,
): Promise<void> {
  await acceptConsent(page);
  const sentence = (await page.getByRole("blockquote").innerText()).trim();
  expect(sentence.split(/\s+/).length).toBeGreaterThan(5);
  await setConsentTranscript(page, transcript(sentence));
  await recordAndUploadConsent(page);
  await uploadSamples(page);
  await submitClone(page, name);
}

async function clonedVoices(page: Page): Promise<VoiceSummary[]> {
  const response = await browserApi(page, "GET", "/v1/voices?limit=100");
  expect(response.status(), await response.text()).toBe(200);
  const body = (await response.json()) as { items: VoiceSummary[] };
  return body.items.filter((voice) => voice.kind === "cloned");
}

test("a user records consent, uploads samples and ends up with a ready default voice that can be deleted", async ({
  page,
}) => {
  test.setTimeout(CLONE_TIMEOUT_MS * 2);
  const name = voiceName();
  await registerApi(page);

  await cloneWithTranscript(page, name, (sentence) => sentence);
  await expect(page.getByText(`${name} is ready to use.`)).toBeVisible({
    timeout: CLONE_TIMEOUT_MS,
  });
  await clearConsentTranscript(page);

  await page.getByRole("link", { name: "Back to your voices", exact: true }).click();
  await expect(page).toHaveURL(/\/settings\/voices$/);
  const cloned = page.getByRole("list", { name: "Your cloned voices" });
  await expect(cloned.getByRole("heading", { name, level: 3 })).toBeVisible();
  await cloned.getByRole("button", { name: `Set ${name} as default`, exact: true }).click();
  await expect(page.getByText(`Your default voice is ${name}.`)).toBeVisible();

  await page.reload();
  await expect(page.getByText(`Your default voice is ${name}.`)).toBeVisible();
  await expect(
    page
      .getByRole("list", { name: "Your cloned voices" })
      .getByRole("button", { name: `${name} is your default voice`, exact: true }),
  ).toBeDisabled();

  await page.getByRole("button", { name: `Delete ${name}`, exact: true }).click();
  await page
    .getByRole("alertdialog")
    .getByRole("button", { name: "Delete voice", exact: true })
    .click();
  await expect(page.getByRole("heading", { name: "No cloned voices yet", level: 3 })).toBeVisible();
  expect(await clonedVoices(page)).toEqual([]);
});

test("a consent transcript that does not match the sentence fails the clone with guidance and leaves no ready voice", async ({
  page,
}) => {
  test.setTimeout(CLONE_TIMEOUT_MS * 2);
  const name = voiceName();
  await registerApi(page);

  await cloneWithTranscript(page, name, () => "tomorrow the weather will be sunny in the harbour");

  await expect(page.getByText("Your voice could not be created.")).toBeVisible({
    timeout: CLONE_TIMEOUT_MS,
  });
  await expect(page.getByText(MISMATCH_GUIDANCE)).toBeVisible();
  const voices = await clonedVoices(page);
  expect(voices.map((voice) => voice.status)).not.toContain("ready");
  expect(voices.find((voice) => voice.name === name)?.failureCode).toBe("consent_mismatch");

  await page.goto("/settings/voices");
  await expect(
    page.getByRole("list", { name: "Your cloned voices" }).getByText("Ready", { exact: true }),
  ).toHaveCount(0);
});

test("the microphone is allowed only on the voices pages", async ({ page }) => {
  await registerApi(page);

  const voices = await page.goto("/settings/voices");
  const wizard = await page.goto("/settings/voices/new");
  const dashboard = await page.goto("/dashboard");

  const policy = (response: typeof voices): string =>
    response?.headers()["permissions-policy"] ?? "";
  expect(policy(voices)).toContain("microphone=(self)");
  expect(policy(voices)).not.toContain("microphone=()");
  expect(policy(wizard)).toContain("microphone=(self)");
  expect(policy(dashboard)).toContain("microphone=()");
  expect(policy(dashboard)).not.toContain("microphone=(self)");
});
