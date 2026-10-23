import { expect, test } from "@playwright/test";

import { expectProblem } from "../../support/billing.js";
import { MediaClient, type RenderBed } from "../../support/media.js";

test.describe("delivery of a completed render", () => {
  let admin: MediaClient;
  let otherAdmin: MediaClient;
  let other: MediaClient;
  let finished: RenderBed;

  test.beforeAll(async ({ playwright }) => {
    test.setTimeout(900000);
    const request = await playwright.request.newContext();
    other = await MediaClient.signup(request);
    admin = await MediaClient.signupAdmin(request);
    otherAdmin = await MediaClient.signupAdmin(request);
    const started = await admin.startGolden();
    finished = await admin.finished(started.id);
  });

  test("the render completes with a ready 16:9 rendition", () => {
    expect(finished.status, finished.errorMessage ?? "").toBe("completed");
    const rendition = finished.renditions.find((item) => item.aspect === "16:9");
    expect(rendition?.status).toBe("ready");
    expect(rendition?.url).toBeTruthy();
  });

  test("the rendition URL answers a range request with 206", async ({ request }) => {
    const url = finished.renditions.find((item) => item.aspect === "16:9")?.url ?? "";

    const response = await request.get(url, { headers: { Range: "bytes=0-1023" } });

    expect(response.status()).toBe(206);
    expect(response.headers()["content-range"]).toMatch(/^bytes 0-1023\//);
    expect((await response.body()).length).toBe(1024);
  });

  test("the rendition URL without its signature is refused", async ({ request }) => {
    const url = finished.renditions.find((item) => item.aspect === "16:9")?.url ?? "";

    const response = await request.get(url.split("?")[0] ?? "");

    expect(response.status()).toBe(403);
  });

  test("another user cannot list the renditions or fetch the test bed render", async () => {
    await expectProblem(await other.renditions(finished.id), 404, "render_not_found");
    await expectProblem(await otherAdmin.renditions(finished.id), 404, "render_not_found");
    await expectProblem(await otherAdmin.bedRender(finished.id), 404, "render_not_found");
  });

  test("no response to another user contains the rendition URL", async () => {
    const url = finished.renditions.find((item) => item.aspect === "16:9")?.url ?? "";
    const objectPath = new URL(url).pathname;

    const bodies = [
      await (await other.renditions(finished.id)).text(),
      await (await otherAdmin.bedRender(finished.id)).text(),
      await (await otherAdmin.render(finished.id)).text(),
    ];

    for (const body of bodies) {
      expect(body).not.toContain(objectPath);
    }
  });

  test("the owner can fetch the rendition list again to refresh the URLs", async () => {
    const response = await admin.renditions(finished.id);

    expect(response.status()).toBe(200);
    const body = (await response.json()) as { items: { url: string | null }[] };
    expect(body.items.every((item) => item.url !== null)).toBe(true);
  });
});
