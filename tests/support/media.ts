import { type APIRequestContext, type APIResponse, expect } from "@playwright/test";

import { signupWithRole } from "./admin.js";
import { BillingSession } from "./billing.js";
import { VoiceUser } from "./voices.js";

export interface RenderState {
  id: string;
  source: string;
  status: string;
  stage: string | null;
  progress: number;
  errorCode: string | null;
  errorMessage: string | null;
}

export interface Rendition {
  id: string;
  aspect: string;
  status: string;
  url: string | null;
  posterUrl: string | null;
  subtitlesUrl: string | null;
}

export interface RenderBed extends RenderState {
  renditions: Rendition[];
}

export interface MediaSession {
  mode: string;
  expiresAt: string | null;
}

export const GOLDEN_NAME = "kinetic-typography";
export const RENDER_TIMEOUT_MS = 600000;
export const TERMINAL_STATUSES = ["completed", "failed", "cancelled"];

export class MediaClient {
  constructor(readonly session: BillingSession) {}

  get userId(): string {
    return this.session.userId;
  }

  static async signup(request: APIRequestContext): Promise<MediaClient> {
    const session = new BillingSession(request);
    await session.signup();
    return new MediaClient(session);
  }

  static async signupAdmin(request: APIRequestContext): Promise<MediaClient> {
    return new MediaClient(await signupWithRole(request, "admin"));
  }

  async mediaSession(): Promise<APIResponse> {
    return this.session.call("GET", "/v1/media/session");
  }

  async render(renderId: string): Promise<APIResponse> {
    return this.session.call("GET", `/v1/renders/${renderId}`);
  }

  async renditions(renderId: string): Promise<APIResponse> {
    return this.session.call("GET", `/v1/renders/${renderId}/renditions`);
  }

  async bedRender(renderId: string): Promise<APIResponse> {
    return this.session.call("GET", `/v1/admin/render/testbed/${renderId}`);
  }

  async bedEvents(renderId: string): Promise<APIResponse> {
    return this.session.call("GET", `/v1/admin/render/testbed/${renderId}/events`);
  }

  async bedCancel(renderId: string): Promise<APIResponse> {
    return this.session.call("POST", `/v1/admin/render/testbed/${renderId}/cancel`);
  }

  async goldenNames(): Promise<string[]> {
    const catalog = await this.session.json<{ items: { name: string }[] }>(
      await this.session.call("GET", "/v1/admin/render/testbed/golden"),
      200,
    );
    return catalog.items.map((item) => item.name);
  }

  async createGolden(voiceId: string, name: string = GOLDEN_NAME): Promise<APIResponse> {
    return this.session.call("POST", `/v1/admin/render/testbed/golden/${name}`, {
      voiceId,
      aspects: ["16:9"],
      subtitles: true,
    });
  }

  async startGolden(): Promise<RenderState> {
    const voiceId = await new VoiceUser(this.session).readyBuiltinVoice();
    return this.session.json<RenderState>(await this.createGolden(voiceId), 202);
  }

  async finished(renderId: string): Promise<RenderBed> {
    let latest: RenderBed | undefined;
    await expect
      .poll(
        async () => {
          latest = await this.session.json<RenderBed>(await this.bedRender(renderId), 200);
          return TERMINAL_STATUSES.includes(latest.status);
        },
        { timeout: RENDER_TIMEOUT_MS, intervals: [1000, 2000, 5000] },
      )
      .toBe(true);
    if (latest === undefined) throw new Error("The render was never read");
    return latest;
  }
}
