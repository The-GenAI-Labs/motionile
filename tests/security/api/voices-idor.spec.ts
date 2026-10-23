import { randomUUID } from "node:crypto";

import { expect, test } from "@playwright/test";

import { upload, wavBytes } from "../../support/audio.js";
import { AuthApi } from "../../support/auth.js";
import { expectProblem } from "../../support/billing.js";
import { type CloneStart, VoiceUser } from "../../support/voices.js";

const missingId = randomUUID();

test.describe("another user's voices and clone attempts", () => {
  let owner: VoiceUser;
  let attempt: CloneStart;
  let sampleId: string;
  let voiceId: string;

  test.describe.configure({ timeout: 180000 });

  test.beforeAll(async ({ playwright }) => {
    test.setTimeout(180000);
    const request = await playwright.request.newContext();
    owner = await VoiceUser.signup(request);
    attempt = await owner.startClone();
    await owner.fillAttempt(attempt);
    sampleId = (await owner.attemptState(attempt.attemptId)).samples[0]?.id ?? "";
    const submittedAttempt = await owner.startClone();
    await owner.fillAttempt(submittedAttempt);
    const submitted = await owner.submit(submittedAttempt.attemptId);
    expect(submitted.status(), await submitted.text()).toBe(202);
    voiceId = submittedAttempt.voiceId;
    await owner.settled(voiceId);
  });

  test("the owner can read the cloned voice and the voice is listed", async () => {
    expect((await owner.voice(voiceId)).status()).toBe(200);
    const listed = await owner.listVoices("?kind=cloned");
    expect(listed.items.map((voice) => voice.id)).toContain(voiceId);
  });

  test("another user gets 404 for the voice and never sees it in a list", async ({ request }) => {
    const other = await VoiceUser.signup(request);

    await expectProblem(await other.voice(voiceId), 404, "voice_not_found");
    const listed = await other.listVoices("?limit=100");
    expect(listed.items.map((voice) => voice.id)).not.toContain(voiceId);
  });

  test("another user gets 404 for the voice preview", async ({ request }) => {
    const other = await VoiceUser.signup(request);

    await expectProblem(await other.preview(voiceId), 404, "voice_not_found");
  });

  test("another user cannot delete the voice and the owner still has it", async ({ request }) => {
    const other = await VoiceUser.signup(request);

    await expectProblem(await other.deleteVoice(voiceId), 404, "voice_not_found");
    expect((await owner.voice(voiceId)).status()).toBe(200);
  });

  test("another user cannot read, extend or submit the clone attempt", async ({ request }) => {
    const other = await VoiceUser.signup(request);

    await expectProblem(await other.attempt(attempt.attemptId), 404, "clone_attempt_not_found");
    await expectProblem(
      await other.addSample(attempt.attemptId, upload(wavBytes(2))),
      404,
      "clone_attempt_not_found",
    );
    await expectProblem(
      await other.putConsent(attempt.attemptId, upload(wavBytes(4))),
      404,
      "clone_attempt_not_found",
    );
    await expectProblem(await other.submit(attempt.attemptId), 404, "clone_attempt_not_found");
    expect((await owner.attemptState(attempt.attemptId)).samples).toHaveLength(1);
  });

  test("another user cannot remove a sample of the owner's attempt", async ({ request }) => {
    const other = await VoiceUser.signup(request);
    const ownAttempt = await other.startClone();

    await expectProblem(
      await other.removeSample(attempt.attemptId, sampleId),
      404,
      "clone_attempt_not_found",
    );
    await expectProblem(
      await other.removeSample(ownAttempt.attemptId, sampleId),
      404,
      "clone_sample_not_found",
    );
  });

  test("a ready built-in voice can be a default voice, the owner's cloned voice cannot", async ({
    request,
  }) => {
    const other = await VoiceUser.signup(request);
    const preferences = await other.session.json<Record<string, unknown>>(
      await other.session.call("GET", "/v1/users/me/preferences"),
      200,
    );

    const response = await other.session.call("PUT", "/v1/users/me/preferences", {
      ...preferences,
      defaultVoiceId: voiceId,
    });

    await expectProblem(response, 422, "voice_not_available");
    const after = (await (await other.session.call("GET", "/v1/users/me/preferences")).json()) as {
      defaultVoiceId: string | null;
    };
    expect(after.defaultVoiceId).toBeNull();
    const builtinId = await (await VoiceUser.signupWithRole(request, "admin")).readyBuiltinVoice();
    const builtin = await other.session.call("PUT", "/v1/users/me/preferences", {
      ...preferences,
      defaultVoiceId: builtinId,
    });
    expect(builtin.status(), await builtin.text()).toBe(200);
  });
});

test.describe("anonymous callers", () => {
  const paths: readonly [string, string][] = [
    ["GET", "/v1/voices"],
    ["GET", `/v1/voices/${missingId}`],
    ["GET", `/v1/voices/${missingId}/preview`],
    ["DELETE", `/v1/voices/${missingId}`],
    ["POST", "/v1/voices/clones"],
    ["GET", `/v1/voices/clones/${missingId}`],
    ["DELETE", `/v1/voices/clones/${missingId}/samples/${missingId}`],
    ["POST", `/v1/voices/clones/${missingId}/submit`],
  ];

  for (const [method, path] of paths) {
    test(`${method} ${path.replaceAll(missingId, "{id}")} answers 401`, async ({ request }) => {
      const anonymous = new AuthApi(request);

      await expectProblem(
        await anonymous.send(method, path, undefined, { "Idempotency-Key": randomUUID() }),
        401,
        "unauthenticated",
      );
    });
  }

  test("uploads answer 401 without a session", async ({ request }) => {
    const anonymous = new AuthApi(request);
    const part = upload(wavBytes(2));

    await expectProblem(
      await anonymous.sendMultipart("POST", `/v1/voices/clones/${missingId}/samples`, {
        file: part,
      }),
      401,
      "unauthenticated",
    );
    await expectProblem(
      await anonymous.sendMultipart("PUT", `/v1/voices/clones/${missingId}/consent-recording`, {
        file: part,
      }),
      401,
      "unauthenticated",
    );
  });
});

test.describe("permission-gated admin routes", () => {
  test.describe.configure({ timeout: 120000 });

  const adminRoutes: readonly [string, string, Record<string, unknown>?][] = [
    ["GET", "/v1/admin/voices"],
    ["POST", "/v1/admin/voices/sync"],
    ["PATCH", `/v1/admin/voices/${missingId}`, { status: "ready" }],
    ["POST", `/v1/admin/voices/${missingId}/preview`],
    ["GET", "/v1/admin/music"],
    ["GET", `/v1/admin/music/${missingId}`],
    ["PATCH", `/v1/admin/music/${missingId}`, { title: "x" }],
    ["POST", `/v1/admin/music/${missingId}/activate`],
    ["POST", `/v1/admin/music/${missingId}/deactivate`],
    ["GET", "/v1/admin/render/testbed/golden"],
    ["GET", "/v1/admin/render/testbed/music-tracks"],
    ["POST", "/v1/admin/render/testbed/golden/kinetic-typography", { voiceId: missingId }],
    ["GET", `/v1/admin/render/testbed/${missingId}`],
    ["GET", `/v1/admin/render/testbed/${missingId}/events`],
    ["POST", `/v1/admin/render/testbed/${missingId}/cancel`],
  ];

  test("a plain user is forbidden from every voice, music and test bed admin route", async ({
    request,
  }) => {
    const user = await VoiceUser.signup(request);
    const statuses: number[] = [];

    for (const [method, path, body] of adminRoutes) {
      statuses.push((await user.session.call(method, path, body)).status());
    }

    expect(new Set(statuses)).toEqual(new Set([403]));
  });

  test("a plain user cannot upload music", async ({ request }) => {
    const user = await VoiceUser.signup(request);

    const response = await user.auth.sendMultipart("POST", "/v1/admin/music", {
      file: upload(wavBytes(2)),
    });

    expect(response.status()).toBe(403);
  });

  test("voice administration answers 404 for cloned voices even to an admin", async ({
    request,
  }) => {
    const admin = await VoiceUser.signupWithRole(request, "admin");
    const owner = await VoiceUser.signup(request);
    const clone = await owner.startClone();

    const response = await admin.session.call("PATCH", `/v1/admin/voices/${clone.voiceId}`, {
      status: "ready",
    });

    expect(response.status()).toBe(404);
  });
});
