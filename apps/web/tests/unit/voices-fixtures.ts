import type {
  AdminVoice,
  CloneAttempt,
  CloneStart,
  Voice,
} from "@/features/voices/types/voices.types";

export const VOICE_ID = "0197c5a2-1b2c-7d3e-8f40-5a6b7c8d9b01";
export const CLONED_ID = "0197c5a2-1b2c-7d3e-8f40-5a6b7c8d9b02";
export const ATTEMPT_ID = "0197c5a2-1b2c-7d3e-8f40-5a6b7c8d9b03";
export const SAMPLE_ID = "0197c5a2-1b2c-7d3e-8f40-5a6b7c8d9b04";

export const voice = (overrides: Partial<Voice> = {}): Voice => ({
  id: VOICE_ID,
  name: "Aria",
  kind: "builtin",
  language: "en",
  status: "ready",
  failureCode: null,
  tags: ["warm", "female"],
  labels: {},
  hasPreview: true,
  createdAt: "2026-10-18T09:30:00.000Z",
  updatedAt: "2026-10-18T09:30:00.000Z",
  ...overrides,
});

export const hindiVoice = voice({
  id: "0197c5a2-1b2c-7d3e-8f40-5a6b7c8d9b05",
  name: "Kavya",
  language: "hi",
  tags: [],
});

export const clonedVoice = voice({
  id: CLONED_ID,
  name: "My voice",
  kind: "cloned",
  tags: [],
});

export const pendingVoice = voice({
  id: "0197c5a2-1b2c-7d3e-8f40-5a6b7c8d9b06",
  name: "Brewing",
  kind: "cloned",
  status: "pending",
  hasPreview: false,
  tags: [],
});

export const failedVoice = voice({
  id: "0197c5a2-1b2c-7d3e-8f40-5a6b7c8d9b07",
  name: "Broken",
  kind: "cloned",
  status: "failed",
  failureCode: "consent_mismatch",
  hasPreview: false,
  tags: [],
});

export const adminVoice = (overrides: Partial<AdminVoice> = {}): AdminVoice => ({
  ...voice(),
  provider: "elevenlabs",
  providerVoiceId: "el-123",
  ...overrides,
});

export const preferences = {
  defaultStyle: null,
  pace: "normal",
  language: "en",
  depth: "standard",
  defaultAspect: "16:9",
  captionsEnabled: true,
  defaultVoiceId: null as string | null,
};

export const cloneStart: CloneStart = {
  attemptId: ATTEMPT_ID,
  voiceId: CLONED_ID,
  consentSentence: "I agree that Motionile may clone my voice. Seven maple harbor 4821.",
  statementText: "I confirm this voice is mine and I consent to it being cloned.",
  statementVersion: "2026-10-19",
  expiresAt: "2026-10-20T12:00:00.000Z",
  limits: {
    sampleMinTotalSeconds: 30,
    sampleMaxTotalSeconds: 300,
    sampleMaxBytes: 26_214_400,
    consentMinSeconds: 3,
    consentMaxSeconds: 30,
    maxSampleFiles: 10,
  },
};

export const attempt = (overrides: Partial<CloneAttempt> = {}): CloneAttempt => ({
  attemptId: ATTEMPT_ID,
  voiceId: CLONED_ID,
  consentSentence: cloneStart.consentSentence,
  statementVersion: cloneStart.statementVersion,
  expiresAt: cloneStart.expiresAt,
  consentRecording: null,
  samples: [],
  totalSampleMs: 0,
  limits: cloneStart.limits,
  ...overrides,
});
