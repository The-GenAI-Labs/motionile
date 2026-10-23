import { randomUUID } from "node:crypto";

import { expect, test } from "@playwright/test";

import { AuthApi } from "../../support/auth.js";
import { expectProblem } from "../../support/billing.js";
import { MediaClient, type RenderState } from "../../support/media.js";

const missingId = randomUUID();

test.describe("render ownership", () => {
  let owner: MediaClient;
  let other: MediaClient;
  let ownerAdmin: MediaClient;
  let otherAdmin: MediaClient;
  let render: RenderState;

  test.beforeAll(async ({ playwright }) => {
    test.setTimeout(180000);
    const request = await playwright.request.newContext();
    owner = await MediaClient.signup(request);
    other = await MediaClient.signup(request);
    ownerAdmin = await MediaClient.signupAdmin(request);
    otherAdmin = await MediaClient.signupAdmin(request);
    render = await ownerAdmin.startGolden();
  });

  test("an admin reads the render they created", async () => {
    const own = await ownerAdmin.bedRender(render.id);

    expect(own.status()).toBe(200);
    expect(((await own.json()) as RenderState).id).toBe(render.id);
    expect((await ownerAdmin.render(render.id)).status()).toBe(200);
    expect((await ownerAdmin.renditions(render.id)).status()).toBe(200);
  });

  test("another user cannot read the render or its renditions", async () => {
    await expectProblem(await other.render(render.id), 404, "render_not_found");
    await expectProblem(await other.renditions(render.id), 404, "render_not_found");
  });

  test("another admin gets 404 for the test bed render, never 403", async () => {
    await expectProblem(await otherAdmin.bedRender(render.id), 404, "render_not_found");
    await expectProblem(await otherAdmin.render(render.id), 404, "render_not_found");
    await expectProblem(await otherAdmin.renditions(render.id), 404, "render_not_found");
  });

  test("another admin cannot open the event stream of the render", async () => {
    await expectProblem(await otherAdmin.bedEvents(render.id), 404, "render_not_found");
  });

  test("another admin cannot cancel the render and the owner's render is untouched", async () => {
    await expectProblem(await otherAdmin.bedCancel(render.id), 404, "render_not_found");

    const after = (await (await ownerAdmin.bedRender(render.id)).json()) as RenderState;
    expect(after.status).not.toBe("cancelled");
  });

  test("a render that does not exist answers like one owned by someone else", async () => {
    const foreign = await otherAdmin.bedRender(render.id);
    const missing = await otherAdmin.bedRender(missingId);

    expect(foreign.status()).toBe(missing.status());
    expect(((await foreign.json()) as { code: string }).code).toBe(
      ((await missing.json()) as { code: string }).code,
    );
  });

  test("a plain user is forbidden from the test bed render routes", async () => {
    const statuses = [
      (await owner.bedRender(render.id)).status(),
      (await owner.bedEvents(render.id)).status(),
      (await owner.bedCancel(render.id)).status(),
    ];

    expect(statuses).toEqual([403, 403, 403]);
  });
});

test.describe("anonymous callers", () => {
  const paths: readonly [string, string][] = [
    ["GET", `/v1/renders/${missingId}`],
    ["GET", `/v1/renders/${missingId}/renditions`],
    ["GET", "/v1/media/session"],
    ["GET", `/v1/admin/render/testbed/${missingId}`],
    ["GET", `/v1/admin/render/testbed/${missingId}/events`],
    ["POST", `/v1/admin/render/testbed/${missingId}/cancel`],
    ["GET", "/v1/admin/render/testbed/golden"],
    ["POST", "/v1/admin/render/testbed/golden/kinetic-typography"],
    ["GET", "/v1/admin/render/testbed/music-tracks"],
  ];

  for (const [method, path] of paths) {
    test(`${method} ${path.replace(missingId, "{id}")} answers 401`, async ({ request }) => {
      const anonymous = new AuthApi(request);

      await expectProblem(await anonymous.send(method, path), 401, "unauthenticated");
    });
  }
});

test("the media session requires authentication and rejects a tampered access token without setting cookies", async ({
  request,
}) => {
  const api = new AuthApi(request);
  await api.signup();
  const [header = "", payload = ""] = (api.cookies.get("__Secure-mo_at") ?? "").split(".");
  api.cookies.set("__Secure-mo_at", `${header}.${payload}.AAAAAAAA`);

  const response = await api.send("GET", "/v1/media/session");

  expect(response.status()).toBe(401);
  expect(response.headersArray().some((header) => /^set-cookie$/i.test(header.name))).toBe(false);
});
