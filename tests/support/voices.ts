import { randomUUID } from "node:crypto";

import { type APIRequestContext, type APIResponse, expect } from "@playwright/test";

import { signupWithRole } from "./admin.js";
import { upload, wavBytes } from "./audio.js";
import type { AuthApi, UploadPart } from "./auth.js";
import { BillingSession } from "./billing.js";

export interface CloneLimits {
  sampleMinTotalSeconds: number;
  sampleMaxTotalSeconds: number;
  sampleMaxBytes: number;
  consentMinSeconds: number;
  consentMaxSeconds: number;
  maxSampleFiles: number;
}

export interface CloneStart {
  attemptId: string;
  voiceId: string;
  consentSentence: string;
  statementText: string;
  statementVersion: string;
  expiresAt: string;
  limits: CloneLimits;
}

export interface CloneAttempt {
  attemptId: string;
  voiceId: string;
  consentRecording: { durationMs: number; sizeBytes: number } | null;
  samples: { id: string; durationMs: number; sizeBytes: number }[];
  totalSampleMs: number;
  limits: CloneLimits;
}

export interface Voice {
  id: string;
  name: string;
  kind: string;
  language: string;
  status: string;
  failureCode: string | null;
  hasPreview: boolean;
}

export interface VoicePage {
  items: Voice[];
  nextCursor: string | null;
}

export interface AdminVoice extends Voice {
  provider: string;
  providerVoiceId: string | null;
}

export interface AdminVoicePage {
  items: AdminVoice[];
  nextCursor: string | null;
}

export interface VoicePreview {
  url: string;
  expiresAt: string;
}

export const CLONE_SAMPLE_SECONDS = 31;
export const CONSENT_SECONDS = 4;

export class VoiceUser {
  constructor(readonly session: BillingSession) {}

  get auth(): AuthApi {
    return this.session.auth;
  }

  get userId(): string {
    return this.session.userId;
  }

  static async signup(request: APIRequestContext): Promise<VoiceUser> {
    const session = new BillingSession(request);
    await session.signup();
    return new VoiceUser(session);
  }

  static async signupWithRole(request: APIRequestContext, role: string): Promise<VoiceUser> {
    return new VoiceUser(await signupWithRole(request, role));
  }

  async statementVersion(): Promise<string> {
    const response = await this.auth.send("GET", "/v1/settings/public");
    const body = (await response.json()) as { settings: Record<string, unknown> };
    return String(body.settings["voices.consent_statement_version"]);
  }

  async start(statementVersion?: string): Promise<APIResponse> {
    return this.session.call("POST", "/v1/voices/clones", {
      statementVersion: statementVersion ?? (await this.statementVersion()),
      accepted: true,
    });
  }

  async startClone(): Promise<CloneStart> {
    return this.session.json<CloneStart>(await this.start(), 201);
  }

  async attempt(attemptId: string): Promise<APIResponse> {
    return this.session.call("GET", `/v1/voices/clones/${attemptId}`);
  }

  async attemptState(attemptId: string): Promise<CloneAttempt> {
    return this.session.json<CloneAttempt>(await this.attempt(attemptId), 200);
  }

  async addSample(attemptId: string, part: UploadPart): Promise<APIResponse> {
    return this.auth.sendMultipart("POST", `/v1/voices/clones/${attemptId}/samples`, {
      file: part,
    });
  }

  async putConsent(attemptId: string, part: UploadPart): Promise<APIResponse> {
    return this.auth.sendMultipart("PUT", `/v1/voices/clones/${attemptId}/consent-recording`, {
      file: part,
    });
  }

  async removeSample(attemptId: string, sampleId: string): Promise<APIResponse> {
    return this.session.call("DELETE", `/v1/voices/clones/${attemptId}/samples/${sampleId}`);
  }

  async submit(
    attemptId: string,
    key: string | null = randomUUID(),
    body: Record<string, unknown> = { name: "My voice", language: "en" },
  ): Promise<APIResponse> {
    return this.session.call(
      "POST",
      `/v1/voices/clones/${attemptId}/submit`,
      body,
      key === null ? {} : { "Idempotency-Key": key },
    );
  }

  async voice(voiceId: string): Promise<APIResponse> {
    return this.session.call("GET", `/v1/voices/${voiceId}`);
  }

  async preview(voiceId: string): Promise<APIResponse> {
    return this.session.call("GET", `/v1/voices/${voiceId}/preview`);
  }

  async deleteVoice(voiceId: string): Promise<APIResponse> {
    return this.session.call("DELETE", `/v1/voices/${voiceId}`);
  }

  async listVoices(query = ""): Promise<VoicePage> {
    return this.session.json<VoicePage>(await this.session.call("GET", `/v1/voices${query}`), 200);
  }

  async fillAttempt(start: CloneStart): Promise<void> {
    expect(
      (await this.putConsent(start.attemptId, upload(wavBytes(CONSENT_SECONDS)))).status(),
    ).toBe(200);
    expect(
      (await this.addSample(start.attemptId, upload(wavBytes(CLONE_SAMPLE_SECONDS)))).status(),
    ).toBe(201);
  }

  async submitClone(): Promise<CloneStart> {
    const start = await this.startClone();
    await this.fillAttempt(start);
    const submitted = await this.submit(start.attemptId);
    expect(submitted.status(), await submitted.text()).toBe(202);
    return start;
  }

  async cloneToCompletion(): Promise<{ start: CloneStart; voice: Voice }> {
    const start = await this.submitClone();
    return { start, voice: await this.settled(start.voiceId) };
  }

  async settled(voiceId: string): Promise<Voice> {
    let latest: Voice | undefined;
    await expect
      .poll(
        async () => {
          latest = await this.session.json<Voice>(await this.voice(voiceId), 200);
          return latest.status;
        },
        { timeout: 90000, intervals: [250, 500, 1000, 2000] },
      )
      .not.toBe("pending");
    if (latest === undefined) throw new Error("The voice was never read");
    return latest;
  }

  async previewOfReadyBuiltinVoice(admin: VoiceUser): Promise<VoicePreview> {
    const voiceId = await admin.readyBuiltinVoice();
    const regenerated = await admin.session.call("POST", `/v1/admin/voices/${voiceId}/preview`);
    expect(regenerated.status(), await regenerated.text()).toBe(200);
    let latest: APIResponse | undefined;
    await expect
      .poll(
        async () => {
          latest = await this.preview(voiceId);
          return latest.status();
        },
        { timeout: 30000, intervals: [250, 500, 1000] },
      )
      .toBe(200);
    if (latest === undefined) throw new Error("The preview was never read");
    return (await latest.json()) as VoicePreview;
  }

  async syncBuiltinVoices(): Promise<AdminVoicePage> {
    const synced = await this.session.call("POST", "/v1/admin/voices/sync");
    expect(synced.status(), await synced.text()).toBe(200);
    return this.session.json<AdminVoicePage>(
      await this.session.call("GET", "/v1/admin/voices?limit=100"),
      200,
    );
  }

  async readyBuiltinVoice(): Promise<string> {
    const page = await this.syncBuiltinVoices();
    const ready = page.items.find(
      (voice) => voice.kind === "builtin" && voice.status === "ready" && voice.language === "en",
    );
    if (ready) return ready.id;
    const candidate = page.items.find(
      (voice) => voice.kind === "builtin" && voice.language === "en",
    );
    if (candidate === undefined) throw new Error("The provider returned no built-in voices");
    const updated = await this.session.call("PATCH", `/v1/admin/voices/${candidate.id}`, {
      status: "ready",
    });
    expect(updated.status(), await updated.text()).toBe(200);
    return candidate.id;
  }
}
