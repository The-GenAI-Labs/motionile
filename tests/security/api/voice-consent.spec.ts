import { randomUUID } from "node:crypto";

import { expect, test } from "@playwright/test";

import { upload, wavBytes } from "../../support/audio.js";
import { expectProblem } from "../../support/billing.js";
import { type CloneStart, CONSENT_SECONDS, VoiceUser } from "../../support/voices.js";

test.describe("consent statement", () => {
  test("a stale statement version is rejected and opens no attempt", async ({ request }) => {
    const user = await VoiceUser.signup(request);

    const response = await user.start("1999-01-01");

    await expectProblem(response, 409, "consent_statement_outdated");
  });

  test("the current statement version opens an attempt with the statement text and a sentence", async ({
    request,
  }) => {
    const user = await VoiceUser.signup(request);

    const start = await user.startClone();

    expect(start.statementVersion).toBe(await user.statementVersion());
    expect(start.statementText.length).toBeGreaterThan(50);
    expect(start.consentSentence.split(/\s+/).length).toBeGreaterThan(5);
  });

  test("two attempts never share a consent sentence", async ({ request }) => {
    const user = await VoiceUser.signup(request);

    const first = await user.startClone();
    const second = await user.startClone();

    expect(second.consentSentence).not.toBe(first.consentSentence);
    expect(second.attemptId).not.toBe(first.attemptId);
  });

  test("acceptance must be explicit", async ({ request }) => {
    const user = await VoiceUser.signup(request);
    const statementVersion = await user.statementVersion();

    const declined = await user.session.call("POST", "/v1/voices/clones", {
      statementVersion,
      accepted: false,
    });
    const omitted = await user.session.call("POST", "/v1/voices/clones", { statementVersion });

    expect(declined.status()).toBe(422);
    expect(omitted.status()).toBe(422);
  });
});

test.describe("clone submission", () => {
  test("submitting without an Idempotency-Key is rejected and creates no voice", async ({
    request,
  }) => {
    const user = await VoiceUser.signup(request);
    const start = await user.startClone();
    await user.fillAttempt(start);

    const missing = await user.submit(start.attemptId, null);

    await expectProblem(missing, 400, "idempotency_key_required");
    expect((await user.listVoices("?kind=cloned")).items).toEqual([]);
    expect((await user.attempt(start.attemptId)).status()).toBe(200);
  });

  test("submitting without a consent recording is rejected", async ({ request }) => {
    const user = await VoiceUser.signup(request);
    const start = await user.startClone();
    expect((await user.addSample(start.attemptId, upload(wavBytes(31)))).status()).toBe(201);

    const response = await user.submit(start.attemptId);

    await expectProblem(response, 422, "consent_recording_missing");
  });

  test("submitting samples shorter than the minimum total is rejected", async ({ request }) => {
    const user = await VoiceUser.signup(request);
    const start = await user.startClone();
    expect(
      (await user.putConsent(start.attemptId, upload(wavBytes(CONSENT_SECONDS)))).status(),
    ).toBe(200);
    expect((await user.addSample(start.attemptId, upload(wavBytes(5)))).status()).toBe(201);

    const response = await user.submit(start.attemptId);

    await expectProblem(response, 422, "samples_too_short");
    expect((await user.listVoices("?kind=cloned")).items).toEqual([]);
  });

  test("submitting twice with the same key creates one voice", async ({ request }) => {
    const user = await VoiceUser.signup(request);
    const start = await user.startClone();
    await user.fillAttempt(start);
    const key = randomUUID();

    const first = await user.submit(start.attemptId, key);
    const second = await user.submit(start.attemptId, key);

    expect(first.status(), await first.text()).toBe(202);
    expect(second.status()).toBe(202);
    const voices = (await user.listVoices("?kind=cloned")).items;
    expect(voices.map((voice) => voice.id)).toEqual([start.voiceId]);
  });
});

test.describe("consent verification", () => {
  test.describe.configure({ timeout: 180000 });

  test("a recording that does not speak the sentence fails the clone with consent_mismatch", async ({
    request,
  }) => {
    const user = await VoiceUser.signup(request);
    const { start, voice } = await user.cloneToCompletion();

    expect(voice.id).toBe(start.voiceId);
    expect(voice.status).toBe("failed");
    expect(voice.failureCode).toBe("consent_mismatch");
    expect(voice.hasPreview).toBe(false);
  });

  test("a failed clone discards its attempt and cannot be selected", async ({ request }) => {
    const user = await VoiceUser.signup(request);
    const { start, voice } = await user.cloneToCompletion();
    const preferences = await user.session.json<Record<string, unknown>>(
      await user.session.call("GET", "/v1/users/me/preferences"),
      200,
    );

    await expectProblem(await user.attempt(start.attemptId), 404, "clone_attempt_not_found");
    const selection = await user.session.call("PUT", "/v1/users/me/preferences", {
      ...preferences,
      defaultVoiceId: voice.id,
    });
    await expectProblem(selection, 422, "voice_not_available");
  });

  test("a failed clone can be deleted and then no longer exists", async ({ request }) => {
    const user = await VoiceUser.signup(request);
    const { voice } = await user.cloneToCompletion();

    const deleted = await user.deleteVoice(voice.id);

    expect(deleted.status()).toBe(204);
    await expectProblem(await user.voice(voice.id), 404, "voice_not_found");
    expect((await user.listVoices("?kind=cloned")).items).toEqual([]);
  });
});

test.describe("cloned voice quota", () => {
  test.describe.configure({ timeout: 180000 });

  const QUOTA = 3;

  test("the fourth concurrent clone submission is rejected with voice_quota_exceeded and a new attempt cannot be opened", async ({
    request,
  }) => {
    const user = await VoiceUser.signup(request);
    const attempts: CloneStart[] = [];
    for (let index = 0; index <= QUOTA; index += 1) {
      const start = await user.startClone();
      await user.fillAttempt(start);
      attempts.push(start);
    }

    const submissions = await Promise.all(attempts.map((start) => user.submit(start.attemptId)));

    const statuses = submissions.map((response) => response.status()).sort();
    expect(statuses).toEqual([202, 202, 202, 409]);
    const rejected = submissions.find((response) => response.status() === 409);
    expect(rejected).toBeDefined();
    if (rejected) await expectProblem(rejected, 409, "voice_quota_exceeded");
    await expectProblem(await user.start(), 409, "voice_quota_exceeded");
  });

  test("a user whose clones have failed can open a new attempt again", async ({ request }) => {
    const user = await VoiceUser.signup(request);
    const { voice } = await user.cloneToCompletion();

    expect(voice.status).toBe("failed");
    expect((await user.start()).status()).toBe(201);
  });
});
