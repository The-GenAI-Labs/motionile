import { expect, type Page } from "@playwright/test";

import { browserApi } from "./browser-session.js";

const CONSENT_TRANSCRIPT_PATH = "/v1/_test/voices/consent-transcript";

export async function setConsentTranscript(page: Page, text: string): Promise<void> {
  const response = await browserApi(page, "POST", CONSENT_TRANSCRIPT_PATH, { text });
  expect(response.status(), await response.text()).toBe(204);
}

export async function clearConsentTranscript(page: Page): Promise<void> {
  const response = await browserApi(page, "DELETE", CONSENT_TRANSCRIPT_PATH);
  expect(response.status(), await response.text()).toBe(204);
}
