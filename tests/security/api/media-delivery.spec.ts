import { expect, test } from "@playwright/test";

import { expectProblem } from "../../support/billing.js";
import { MediaClient, type MediaSession, type RenderState } from "../../support/media.js";
import { type VoicePreview, VoiceUser } from "../../support/voices.js";

test.describe("presigned media delivery", () => {
  let user: MediaClient;
  let admin: MediaClient;
  let other: MediaClient;
  let render: RenderState;
  let voicePreview: VoicePreview;

  test.beforeAll(async ({ playwright }) => {
    test.setTimeout(180000);
    const request = await playwright.request.newContext();
    user = await MediaClient.signup(request);
    other = await MediaClient.signup(request);
    admin = await MediaClient.signupAdmin(request);
    render = await admin.startGolden();
    voicePreview = await new VoiceUser(user.session).previewOfReadyBuiltinVoice(
      new VoiceUser(admin.session),
    );
  });

  test("the media session reports presigned mode and sets no cookies", async () => {
    const response = await user.mediaSession();

    expect(response.status()).toBe(200);
    const body = (await response.json()) as MediaSession;
    expect(body.mode).toBe("presigned");
    expect(body.expiresAt).toBeNull();
    expect(response.headers()["cache-control"]).toBe("no-store");
    expect(response.headersArray().some((header) => /^set-cookie$/i.test(header.name))).toBe(false);
  });

  test("a render that has not finished exposes no media URL to its owner", async () => {
    const response = await admin.renditions(render.id);

    expect(response.status()).toBe(200);
    const body = (await response.json()) as { items: { url: string | null }[] };
    expect(body.items.every((item) => item.url === null)).toBe(true);
  });

  test("another user gets 404 for the renditions of the render", async () => {
    await expectProblem(await other.renditions(render.id), 404, "render_not_found");
    await expectProblem(await other.render(render.id), 404, "render_not_found");
  });

  test("a presigned preview URL serves a byte range with 206", async ({ request }) => {
    const response = await request.get(voicePreview.url, { headers: { Range: "bytes=0-63" } });

    expect(response.status()).toBe(206);
    expect(response.headers()["content-range"]).toMatch(/^bytes 0-63\//);
    expect((await response.body()).length).toBe(64);
  });

  test("a presigned preview URL without its signature is refused", async ({ request }) => {
    const unsigned = voicePreview.url.split("?")[0] ?? "";

    const response = await request.get(unsigned);

    expect(response.status()).toBe(403);
  });

  test("a presigned preview URL with a tampered signature is refused", async ({ request }) => {
    const tampered = new URL(voicePreview.url);
    const signature = tampered.searchParams.get("X-Amz-Signature") ?? "";
    tampered.searchParams.set(
      "X-Amz-Signature",
      signature.replace(/^./, signature.startsWith("0") ? "1" : "0"),
    );

    const response = await request.get(tampered.toString());

    expect(response.status()).toBe(403);
  });

  test("a presigned preview URL cannot be redirected to another object key", async ({
    request,
  }) => {
    const redirected = new URL(voicePreview.url);
    redirected.pathname = redirected.pathname.replace(/[^/]+$/, "other.mp3");

    const response = await request.get(redirected.toString());

    expect(response.status()).toBe(403);
  });
});
