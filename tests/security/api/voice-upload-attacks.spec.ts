import { Buffer } from "node:buffer";

import { expect, test } from "@playwright/test";

import {
  HTML_BYTES,
  mp3WithCoverBytes,
  PE_BYTES,
  PNG_BYTES,
  TEXT_BYTES,
  upload,
  wavBytes,
  ZIP_BYTES,
} from "../../support/audio.js";
import { expectProblem } from "../../support/billing.js";
import { type CloneStart, VoiceUser } from "../../support/voices.js";

interface Rejection {
  label: string;
  content: Buffer;
  name: string;
  mimeType: string;
  status: number;
  code: string;
}

const validWav = wavBytes(4);

function rejection(
  label: string,
  content: Buffer,
  code: string,
  name = "recording.wav",
  mimeType = "audio/wav",
  status = 422,
): Rejection {
  return { label, content, name, mimeType, status, code };
}

const REJECTIONS: Rejection[] = [
  rejection("plain text labelled as wav", TEXT_BYTES, "audio_not_audio"),
  rejection("a PNG labelled as wav", PNG_BYTES, "audio_not_audio"),
  rejection("a ZIP archive labelled as wav", ZIP_BYTES, "audio_not_audio", "voice.wav"),
  rejection(
    "a Windows executable labelled as mp3",
    PE_BYTES,
    "audio_not_audio",
    "voice.mp3",
    "audio/mpeg",
  ),
  rejection(
    "an HTML page labelled as audio",
    HTML_BYTES,
    "audio_not_audio",
    "voice.html",
    "audio/wav",
  ),
  rejection("an empty file", Buffer.alloc(0), "audio_not_audio"),
  rejection(
    "a PNG prefix before a valid WAV",
    Buffer.concat([PNG_BYTES, validWav]),
    "audio_not_audio",
  ),
  rejection(
    "a ZIP prefix before a valid WAV",
    Buffer.concat([ZIP_BYTES, validWav]),
    "audio_not_audio",
  ),
  rejection(
    "a PE prefix before a valid WAV",
    Buffer.concat([PE_BYTES, validWav]),
    "audio_not_audio",
  ),
  rejection(
    "an HTML prefix before a valid WAV",
    Buffer.concat([HTML_BYTES, validWav]),
    "audio_not_audio",
  ),
  rejection(
    "a bare RIFF header without audio data",
    validWav.subarray(0, 12),
    "audio_probe_failed",
  ),
  rejection(
    "an MP3 that carries a cover picture stream",
    mp3WithCoverBytes(),
    "audio_video_stream_present",
    "voice.mp3",
    "audio/mpeg",
  ),
  rejection("a clip shorter than the minimum", wavBytes(0.4), "audio_too_short"),
  rejection(
    "text with a path traversal filename",
    TEXT_BYTES,
    "audio_not_audio",
    "../../../../etc/passwd",
    "text/plain",
  ),
  rejection(
    "a PNG with a Windows traversal filename and an audio content type",
    PNG_BYTES,
    "audio_not_audio",
    "..\\..\\windows\\system32\\drivers\\etc\\hosts.wav",
  ),
];

test.describe("voice upload attacks are rejected and nothing is stored", () => {
  test.describe.configure({ mode: "serial" });

  let user: VoiceUser;
  let attempt: CloneStart;

  test.beforeAll(async ({ playwright }) => {
    user = await VoiceUser.signup(await playwright.request.newContext());
    attempt = await user.startClone();
  });

  async function expectEmptyAttempt(): Promise<void> {
    const state = await user.attemptState(attempt.attemptId);
    expect(state.samples).toEqual([]);
    expect(state.consentRecording).toBeNull();
    expect(state.totalSampleMs).toBe(0);
  }

  for (const attack of REJECTIONS) {
    test(`sample upload of ${attack.label} answers ${attack.code}`, async () => {
      const response = await user.addSample(
        attempt.attemptId,
        upload(attack.content, attack.name, attack.mimeType),
      );

      await expectProblem(response, attack.status, attack.code);
      await expectEmptyAttempt();
    });

    test(`consent recording upload of ${attack.label} answers ${attack.code}`, async () => {
      const response = await user.putConsent(
        attempt.attemptId,
        upload(attack.content, attack.name, attack.mimeType),
      );

      await expectProblem(response, attack.status, attack.code);
      await expectEmptyAttempt();
    });
  }

  test("a consent recording longer than the limit answers audio_too_long", async () => {
    const tooLong = wavBytes(attempt.limits.consentMaxSeconds + 2);

    await expectProblem(
      await user.putConsent(attempt.attemptId, upload(tooLong)),
      422,
      "audio_too_long",
    );
    await expectEmptyAttempt();
  });

  test("a consent recording shorter than the minimum answers audio_too_short", async () => {
    const tooShort = wavBytes(attempt.limits.consentMinSeconds - 1);

    await expectProblem(
      await user.putConsent(attempt.attemptId, upload(tooShort)),
      422,
      "audio_too_short",
    );
    await expectEmptyAttempt();
  });

  test("a sample one byte over the size limit answers 413 audio_too_large", async () => {
    const oversize = Buffer.alloc(attempt.limits.sampleMaxBytes + 1);

    await expectProblem(
      await user.addSample(attempt.attemptId, upload(oversize)),
      413,
      "audio_too_large",
    );
    await expectEmptyAttempt();
  });

  test("a consent recording one byte over the size limit answers 413 audio_too_large", async () => {
    const oversize = Buffer.alloc(attempt.limits.sampleMaxBytes + 1);

    await expectProblem(
      await user.putConsent(attempt.attemptId, upload(oversize)),
      413,
      "audio_too_large",
    );
    await expectEmptyAttempt();
  });

  test("an unexpected extra multipart field is rejected", async () => {
    const response = await user.auth.sendMultipart(
      "POST",
      `/v1/voices/clones/${attempt.attemptId}/samples`,
      { file: upload(validWav), note: upload(TEXT_BYTES, "note.txt", "text/plain") },
    );

    await expectProblem(response, 422, "validation_failed");
    await expectEmptyAttempt();
  });

  test("a request without a file part is rejected", async () => {
    const response = await user.auth.sendMultipart(
      "POST",
      `/v1/voices/clones/${attempt.attemptId}/samples`,
      { note: upload(TEXT_BYTES, "note.txt", "text/plain") },
    );

    expect(response.status()).toBe(422);
    await expectEmptyAttempt();
  });
});

test.describe("valid audio is judged by its content and stored only as a clean transcode", () => {
  test.describe.configure({ mode: "serial" });

  const WAV_BYTES_PER_MS = 88.2;
  const WAV_SLACK_BYTES = 4096;

  let user: VoiceUser;
  let attempt: CloneStart;

  test.beforeAll(async ({ playwright }) => {
    user = await VoiceUser.signup(await playwright.request.newContext());
    attempt = await user.startClone();
  });

  test("a WAV labelled as an image with a traversal filename is accepted as audio", async () => {
    const response = await user.addSample(
      attempt.attemptId,
      upload(validWav, "../../../../etc/cron.d/backdoor.png", "image/png"),
    );

    expect(response.status(), await response.text()).toBe(201);
    const state = await user.attemptState(attempt.attemptId);
    expect(state.samples).toHaveLength(1);
    expect(JSON.stringify(state)).not.toContain("etc/cron.d");
    expect(JSON.stringify(state)).not.toContain("backdoor");
  });

  for (const [label, trailer] of [
    ["a PNG", PNG_BYTES],
    ["a ZIP archive", ZIP_BYTES],
    ["a Windows executable", PE_BYTES],
    ["an HTML page", HTML_BYTES],
  ] as const) {
    test(`a WAV followed by ${label} stores no more than the transcoded audio`, async () => {
      const padded = Buffer.concat([validWav, trailer, Buffer.alloc(200000, 0x41)]);

      const response = await user.addSample(attempt.attemptId, upload(padded));

      if (response.status() === 201) {
        const state = await user.attemptState(attempt.attemptId);
        const stored = state.samples[state.samples.length - 1];
        expect(stored).toBeDefined();
        expect(stored?.sizeBytes).toBeLessThanOrEqual(
          (stored?.durationMs ?? 0) * WAV_BYTES_PER_MS + WAV_SLACK_BYTES,
        );
      } else {
        await expectProblem(response, 422, "audio_not_audio");
      }
    });
  }

  test("a consent recording labelled as an executable is stored as a clean WAV", async () => {
    const response = await user.putConsent(
      attempt.attemptId,
      upload(wavBytes(4), "consent.exe", "application/x-msdownload"),
    );

    expect(response.status(), await response.text()).toBe(200);
    const state = await user.attemptState(attempt.attemptId);
    expect(state.consentRecording?.sizeBytes).toBeLessThanOrEqual(
      (state.consentRecording?.durationMs ?? 0) * WAV_BYTES_PER_MS + WAV_SLACK_BYTES,
    );
  });
});
